"""对 deep_research_supervisor_parallelism 数据集运行评估, 并把结果上传到 LangSmith。

执行流程:

    1. target = supervisor_agent 的 supervisor 节点**单步** (不跑子研究智能体,
       只评估并行委托决策本身 —— 一次 LLM 调用, 很轻)
    2. 两个评估器:
       - evaluate_parallelism        : 确定性。ConductResearch 调用数是否等于
         ground-truth num_expected_threads
       - evaluate_delegation_quality : LLM-as-judge。委托的 research_topic 指令
         是否完整覆盖用户问题、互不重叠、自包含

实现说明:

    * 评估只统计 ConductResearch 调用 —— supervisor 在
      委托同时再补一次 think_tool 是合法行为, 不应因此判错; 而 ResearchComplete
      / 纯 think_tool 不计入, 该并行时没并行照样得 0 分。
    * target 不直接返回 Command 对象, 而是抽出工具调用摘要的纯 dict, 便于
      LangSmith 持久化与 fetch 脚本回读。

用法::

    cd deep_research_skills
    python -m scripts.supervisor.run_supervisor_eval                 # 跑全量 (10 条)
    python -m scripts.supervisor.run_supervisor_eval --limit 1       # 冒烟
    python -m scripts.supervisor.run_supervisor_eval --judge-role SUPERVISOR  # judge 复用 supervisor 模型

前置条件::

    1. 已通过 scripts/supervisor/upload_supervisor_dataset.py 创建数据集
    2. .env 中已配置 LANGSMITH_API_KEY + SUPERVISOR_MODEL + JUDGE_MODEL
"""

from __future__ import annotations

# IMPORTANT: load_dotenv() 必须在任何 deep_research.* 之前调用,
# 因为 multi_agent_supervisor 在模块导入时就会实例化
# supervisor_model = get_chat_model("SUPERVISOR") (并连带导入 researcher 侧模型),
# 而这些调用需要 LLM_API_KEY / SUPERVISOR_MODEL 等已经在 os.environ 中.
from dotenv import load_dotenv

load_dotenv()

import argparse
import asyncio
import os
import sys
import uuid
from typing import Any, cast

from langchain_core.messages import convert_to_messages
from langchain_core.runnables import RunnableConfig
from langsmith import Client
from pydantic import BaseModel, Field

from deep_research.model_config import get_chat_model
from deep_research.multi_agent_supervisor import supervisor_agent
from deep_research.prompts import SUPERVISOR_DELEGATION_PROMPT
from deep_research.structured_output_fallback import (
    invoke_with_structured_output_fallback,
)

from scripts._eval_retry import with_retry


# ============================================================
# 评估器使用的结构化输出 Schema
# ============================================================


class DelegationEvaluation(BaseModel):
    """一组委托指令 (research_topic) 的质量判定结果。"""

    reasoning: str = Field(
        description="逐项判定依据, 引用指令中的具体表述作为证据"
    )
    covers_question: bool = Field(
        description="所有委托指令合在一起是否完整覆盖用户问题明确要求的对象与维度"
    )
    no_overlap: bool = Field(
        description="多条指令之间是否清晰、独立、互不重叠 (单条指令时只要内部不自相矛盾即为 True)"
    )
    self_contained: bool = Field(
        description="每条指令是否自包含且具体 (不依赖外部上下文 / 无未展开缩写 / 至少一段话的信息量)"
    )


# ============================================================
# 评估器函数
# ============================================================

# 由 CLI 参数注入, evaluate_* 通过模块级变量读取,
# 这样既不污染 evaluate_* 的签名 (LangSmith 要求 (outputs, reference_outputs)),
# 又能让 judge 模型可配置.
_JUDGE_ROLE: str = "JUDGE"


def _make_judge_model():
    """按 ``_JUDGE_ROLE`` 实例化 judge LLM。"""
    return get_chat_model(_JUDGE_ROLE)


def evaluate_parallelism(outputs: dict, reference_outputs: dict) -> dict:
    """确定性评估: ConductResearch 调用数是否等于期望的并行研究线程数。"""
    expected = int(reference_outputs["num_expected_threads"])

    # target_func 抛错时 LangSmith 仍会调 evaluator, outputs 为 {} —— 直接 0 分,
    # 不让 evaluator 也跟着 KeyError 把这一例的 feedback 写不出去.
    if not outputs or "num_conduct_research" not in outputs:
        return {
            "key": "correct_next_step",
            "score": 0.0,
            "comment": "outputs empty or missing (target error)",
            "value": {"expected_threads": expected},
        }

    actual = int(outputs.get("num_conduct_research") or 0)
    tool_names = [tc.get("name") for tc in (outputs.get("tool_calls") or [])]

    return {
        "key": "correct_next_step",
        "score": 1.0 if actual == expected else 0.0,
        "comment": (
            f"expected {expected} ConductResearch, got {actual}; "
            f"tool_calls={tool_names}"
        ),
        # value 是 Feedback 唯一可承载任意 JSON 的字段, 服务端会持久化, fetch 可读回.
        # metadata 被 SDK 忽略; extra 被服务端覆盖. 详见 scoping eval 同款注释.
        "value": {
            "expected_threads": expected,
            "actual_conduct_research": actual,
            "tool_calls": tool_names,
            "research_topics": outputs.get("research_topics") or [],
        },
    }


def evaluate_delegation_quality(outputs: dict) -> dict:
    """LLM judge: 委托的 research_topic 指令是否覆盖问题、互不重叠、自包含。"""
    research_brief = outputs.get("research_brief") or ""
    research_topics = outputs.get("research_topics") or []

    # 没发出任何 ConductResearch (target 出错 / 直接 ResearchComplete / 只 think) →
    # 没有可评的委托指令, 0 分 + 跳过 judge LLM 调用.
    if not research_topics:
        return {
            "key": "delegation_quality_score",
            "score": 0.0,
            "comment": "no ConductResearch calls — nothing delegated",
            "value": {"research_topics": []},
        }

    topics_block = "\n".join(
        f"{idx}. {topic}" for idx, topic in enumerate(research_topics, 1)
    )

    model = _make_judge_model()
    response = cast(
        DelegationEvaluation,
        with_retry(invoke_with_structured_output_fallback)(
            model,
            DelegationEvaluation,
            SUPERVISOR_DELEGATION_PROMPT.format(
                research_brief=research_brief,
                research_topics=topics_block,
            ),
        ),
    )

    checks = {
        "covers_question": response.covers_question,
        "no_overlap": response.no_overlap,
        "self_contained": response.self_contained,
    }
    passed = sum(1 for ok in checks.values() if ok)

    return {
        "key": "delegation_quality_score",
        "score": passed / len(checks),
        "comment": (
            f"{passed}/{len(checks)} checks passed "
            f"({', '.join(f'{k}={v}' for k, v in checks.items())})"
        ),
        "value": {
            "checks": checks,
            "reasoning": response.reasoning,
            "research_topics": research_topics,
        },
    }


# ============================================================
# Target function
# ============================================================


def _invoke_supervisor_node(state: dict[str, Any], config: RunnableConfig):
    """同步外壳: supervisor 节点是 async 函数, 在每次调用里起独立事件循环。

    LangSmith evaluate 的并发是线程池, 每个 worker 线程各自 asyncio.run 互不干扰;
    放在 with_retry 内层, 重试时也会拿到全新的事件循环。
    """
    return asyncio.run(
        supervisor_agent.nodes["supervisor"].ainvoke(state, config=config)
    )


def target_func(inputs: dict[str, Any]) -> dict[str, Any]:
    """对单条 example 跑 supervisor 节点单步, 返回并行决策的摘要 dict。"""
    # LangSmith 读回的 example inputs 是纯 JSON dict; 这里不经过 LangGraph 的
    # add_messages 通道 (绕过了 graph.invoke), 必须显式还原成 BaseMessage.
    messages = convert_to_messages(list(inputs["supervisor_messages"]))

    config: RunnableConfig = {"configurable": {"thread_id": str(uuid.uuid4())}}
    command = with_retry(_invoke_supervisor_node)(
        {"supervisor_messages": messages}, config
    )

    response = command.update["supervisor_messages"][-1]
    tool_calls = getattr(response, "tool_calls", None) or []
    conduct_research_calls = [
        tc for tc in tool_calls if tc.get("name") == "ConductResearch"
    ]

    return {
        "research_brief": str(messages[0].content),
        "tool_calls": [
            {"name": tc.get("name"), "args": tc.get("args", {})}
            for tc in tool_calls
        ],
        "num_conduct_research": len(conduct_research_calls),
        "research_topics": [
            str(tc.get("args", {}).get("research_topic", ""))
            for tc in conduct_research_calls
        ],
        "assistant_content": str(response.content or ""),
    }


# ============================================================
# CLI
# ============================================================


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dataset-name",
        default=os.getenv("LANGSMITH_DATASET", "deep_research_supervisor_parallelism"),
        help="LangSmith 数据集名称 (默认 deep_research_supervisor_parallelism)",
    )
    parser.add_argument(
        "--experiment-prefix",
        default="Deep Research Supervisor",
        help="实验名称前缀 (默认 'Deep Research Supervisor')",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="只评估前 N 条 examples (默认评估全量), 适合冒烟",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=1,
        help=(
            "并发跑 example 的最大数 (默认 1)。"
            " 每条 example = 1 次 supervisor LLM 调用 + 1 次 judge 调用, 本身很轻;"
            " 但部分 LLM 网关在突发负载下会硬限流 (429/504/空补全), 默认保持 1。"
        ),
    )
    parser.add_argument(
        "--judge-role",
        default="JUDGE",
        help=(
            "判定委托质量的 judge 模型角色 (默认 JUDGE, 即用 .env 里的 JUDGE_MODEL)。"
            " SUPERVISOR_MODEL 若指向 qwen 等不支持 enable_thinking 参数的端点,"
            " judge 会无法产出 feedback; 默认走 JUDGE_MODEL 避免该坑."
            " 想让 judge 复用 supervisor 模型: --judge-role SUPERVISOR"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    global _JUDGE_ROLE
    _JUDGE_ROLE = args.judge_role

    api_key = os.getenv("LANGSMITH_API_KEY")
    if not api_key:
        print("ERROR: LANGSMITH_API_KEY 环境变量未设置", file=sys.stderr)
        return 1

    # 提前实例化一次 judge, 触发 env 校验 (而不是等到批量评估中途才失败)
    try:
        _make_judge_model()
    except RuntimeError as exc:
        print(f"ERROR: 无法实例化 judge 模型: {exc}", file=sys.stderr)
        print(
            f"       (--judge-role={args.judge_role}, 需要 {args.judge_role.upper()}_MODEL 已配置)",
            file=sys.stderr,
        )
        return 1

    client = Client(api_key=api_key)

    if not client.has_dataset(dataset_name=args.dataset_name):
        print(
            f"ERROR: 数据集 '{args.dataset_name}' 不存在。\n"
            f"请先运行: python -m scripts.supervisor.upload_supervisor_dataset",
            file=sys.stderr,
        )
        return 1

    if args.limit is not None:
        data: Any = list(
            client.list_examples(dataset_name=args.dataset_name, limit=args.limit)
        )
        print(f"将评估 {len(data)} 条 examples (--limit={args.limit})")
    else:
        data = args.dataset_name
        print(f"将评估数据集 '{args.dataset_name}' 的全量 examples")

    print(f"实验前缀  : {args.experiment_prefix}")
    print(f"judge 角色: {args.judge_role}")
    print(f"最大并发  : {args.max_concurrency}")
    print()

    result = client.evaluate(
        target_func,
        data=data,
        evaluators=[evaluate_parallelism, evaluate_delegation_quality],
        experiment_prefix=args.experiment_prefix,
        max_concurrency=args.max_concurrency,
        # 单条 example 失败 (如网关偶发 429/504/空补全重试耗尽) 只 log 不中断,
        # 让批量评估能跑完, 失败条目在 LangSmith UI 标红供逐条排查.
        error_handling="log",
    )

    print()
    print("评估已完成。")
    experiment_name = getattr(result, "experiment_name", None)
    if experiment_name:
        print(f"实验名 : {experiment_name}")
    print("到 LangSmith UI 查看详细结果: https://smith.langchain.com/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
