"""对 deep_research_agent_quality 数据集运行端到端评估, 并把结果上传到 LangSmith。

镜像 scripts/scoping/run_scoping_eval.py 的整体形态, 只是:

  1. target = researcher_agent (走完整 search/think/compress 循环)
  2. 评分器换成 evaluate_criteria_coverage + evaluate_citation_grounding

用法::

    cd deep_research_skills
    python -m scripts.research_agent.run_research_eval                  # 跑全量 (10 条)
    python -m scripts.research_agent.run_research_eval --limit 1        # 冒烟
    python -m scripts.research_agent.run_research_eval --judge-role RESEARCHER  # 让 judge 复用 researcher 模型

前置条件::

    1. 已通过 scripts/research_agent/upload_research_dataset.py 创建数据集
    2. .env 中已配置 LANGSMITH_API_KEY + RESEARCHER_MODEL / SUMMARIZATION_MODEL / COMPRESSION_MODEL + JUDGE_MODEL
"""

from __future__ import annotations

# IMPORTANT: load_dotenv() 必须在任何 deep_research.* 之前调用,
# 因为 research_agent_skills 在模块导入时就会实例化 model = get_chat_model("RESEARCHER"),
# 而该调用需要 OPENAI_API_KEY / RESEARCHER_MODEL 等已经在 os.environ 中.
from dotenv import load_dotenv

load_dotenv()

import argparse
import os
import sys
import threading
import uuid
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langsmith import Client
from pydantic import BaseModel, Field

from deep_research.model_config import get_chat_model
from deep_research.prompts import (
    RESEARCH_COVERAGE_PROMPT,
    RESEARCH_GROUNDING_PROMPT,
)
from deep_research.research_agent_skills import (
    researcher_agent_skills as researcher_agent,
)
from deep_research.structured_output_fallback import (
    invoke_with_structured_output_fallback,
)

from scripts._eval_retry import with_retry


# ============================================================
# 评估器使用的结构化输出 Schema
# ============================================================


class Criteria(BaseModel):
    """单条研究维度的覆盖判定结果。"""

    criteria_text: str = Field(
        description="被评估的具体研究维度 (例如 '列出 Llama 3 各模型的参数规模')"
    )
    reasoning: str = Field(
        description="详细说明该维度为何被 / 未被研究报告覆盖, 应包含报告中的具体证据片段"
    )
    is_captured: bool = Field(
        description="该维度是否被研究报告充分覆盖 (True) 或缺失 / 不充分 (False)"
    )


class ClaimGrounding(BaseModel):
    """单条抽出的可验证事实声明及其接地判定。"""

    claim: str = Field(
        description="从研究报告中抽出的一条具体、可验证的事实声明 (数字 / 日期 / 人名 / 产品 / 量化对比 / 引述)"
    )
    is_grounded: bool = Field(
        description="True 表示该声明所在句子带有 [N] 内联标记且 N 在 Sources 段中能找到对应 URL; 否则 False"
    )
    reasoning: str = Field(
        description="判定理由: grounded 需指出引用编号 + Sources 条目; ungrounded 需指出缺失原因"
    )


class GroundingEvaluation(BaseModel):
    """整份研究报告的引用接地评估。"""

    claims: list[ClaimGrounding] = Field(
        description="抽取的所有可验证事实声明 (5-10 条; 报告极短时至少 3 条; 无可验证声明时可为空列表)"
    )
    has_sources_section: bool = Field(
        description="报告末尾是否存在列出引用编号与 URL 对应关系的段 (### Sources / Sources / 来源 / ## 来源 等)"
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


# judge LLM 调用的全局并发上限。与 example/agent 并发 (client.evaluate max_concurrency) 解耦:
# agent 可高并发跑搜索, 但 judge 调用另设更低上限, 避免多个 example 同时判分把 gateway 打到 429。
# 在 main() 中按 --judge-concurrency 重建。
_JUDGE_SEMAPHORE = threading.BoundedSemaphore(2)


def _judge_invoke_once(model, schema, prompt):
    """单次 judge 结构化输出调用, 占用一个全局 judge 并发槽。"""
    with _JUDGE_SEMAPHORE:
        return invoke_with_structured_output_fallback(model, schema, prompt)


def _judge_invoke(model, schema, prompt):
    """judge 调用 = 全局并发受限 + 失败按 RETRY_DELAYS 退避重试。

    semaphore 在每次尝试内部获取/释放, 因此重试退避的 sleep 发生在槽位之外,
    退避期间不占用 judge 并发槽。
    """
    return with_retry(_judge_invoke_once)(model, schema, prompt)


def evaluate_criteria_coverage(outputs: dict, reference_outputs: dict) -> dict:
    """逐条 (per criterion) 判断 compressed_research 是否覆盖了 ground-truth criteria。"""
    compressed_research = outputs.get("compressed_research") or ""
    success_criteria = reference_outputs["criteria"]

    # target_func 抛错时 LangSmith 仍会调 evaluator, outputs 为 {}; 或 agent 静默返回空研究 (Task 7 e2e 实测).
    # 直接报 0 + 跳过 judge LLM 调用, 不让 evaluator 也跟着 KeyError 把这一例的 feedback 写不出去.
    if not compressed_research:
        return {
            "key": "criteria_coverage_score",
            "score": 0.0,
            "comment": "compressed_research empty or missing",
            "value": {"individual_evaluations": []},
        }

    model = _make_judge_model()
    # 逐条 criterion 调 judge; 全局 judge 并发由 _JUDGE_SEMAPHORE 限制 (跨并发 example 生效),
    # 每条独立重试 —— 单条瞬时失败只重试该条, 不连累其余 criterion。
    responses = cast(
        list[Criteria],
        [
            _judge_invoke(
                model,
                Criteria,
                RESEARCH_COVERAGE_PROMPT.format(
                    criterion=criterion,
                    compressed_research=compressed_research,
                ),
            )
            for criterion in success_criteria
        ],
    )

    individual_evaluations = [
        Criteria(
            reasoning=response.reasoning,
            criteria_text=criterion,
            is_captured=response.is_captured,
        )
        for criterion, response in zip(success_criteria, responses)
    ]

    captured = sum(1 for r in individual_evaluations if r.is_captured)
    total = len(individual_evaluations)

    return {
        "key": "criteria_coverage_score",
        "score": captured / total if total > 0 else 0.0,
        "comment": f"{captured}/{total} criteria captured",
        # value 是 Feedback 唯一可承载任意 JSON 的字段, 服务端会持久化, fetch 可读回.
        # metadata 被 SDK 忽略; extra 被服务端覆盖. 详见 scoping eval 同款注释.
        "value": {
            "individual_evaluations": [
                {
                    "criteria": r.criteria_text,
                    "captured": r.is_captured,
                    "reasoning": r.reasoning,
                }
                for r in individual_evaluations
            ],
        },
    }


def evaluate_citation_grounding(outputs: dict) -> dict:
    """判断 compressed_research 中的具体事实声明是否被引用来源所支撑。"""
    compressed_research = outputs.get("compressed_research") or ""

    # 同 evaluate_criteria_coverage: target_func 抛错或 agent 返空时短路, 0 分 + 跳过 judge.
    if not compressed_research:
        return {
            "key": "citation_grounding_score",
            "score": 0.0,
            "comment": "compressed_research empty or missing",
            "value": {"has_sources_section": False, "claims": []},
        }

    model = _make_judge_model()
    response = cast(
        GroundingEvaluation,
        _judge_invoke(
            model,
            GroundingEvaluation,
            RESEARCH_GROUNDING_PROMPT.format(compressed_research=compressed_research),
        ),
    )

    grounded = sum(1 for c in response.claims if c.is_grounded)
    total = len(response.claims)
    # total=0 → 0.0: prompt 要求抽 5-10 条具体声明, 只在"报告全是空泛评论"时允许返回空 claims.
    # 走到 total=0 = 报告本身没有可验证事实 = 研究质量信号本身就是失败, 0 分正确反映这一点
    # (不是 judge 抽取失误 —— 那种会在 with_retry 层面以 ValidationError/ValueError 触发重试).
    score = (grounded / total) if total > 0 else 0.0
    # 缺 Sources 段 → 硬错直接归零 (无论 claims 抽取结果如何)
    if not response.has_sources_section:
        score = 0.0

    return {
        "key": "citation_grounding_score",
        "score": score,
        "comment": (
            f"{grounded}/{total} claims grounded; "
            f"sources_section={response.has_sources_section}"
        ),
        "value": {
            "has_sources_section": response.has_sources_section,
            "claims": [c.model_dump() for c in response.claims],
        },
    }


# ============================================================
# Target function
# ============================================================


def target_func(inputs: dict[str, Any]) -> dict[str, Any]:
    """对单条 example 调用 researcher_agent, 返回 ResearcherOutputState (含 compressed_research)。"""
    config: RunnableConfig = {"configurable": {"thread_id": str(uuid.uuid4())}}
    return cast(
        dict[str, Any],
        with_retry(researcher_agent.invoke)(inputs, config=config),
    )


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
        default=os.getenv("LANGSMITH_DATASET", "deep_research_agent_quality"),
        help="LangSmith 数据集名称 (默认 deep_research_agent_quality)",
    )
    parser.add_argument(
        "--experiment-prefix",
        default="Deep Research Agent",
        help="实验名称前缀 (默认 'Deep Research Agent')",
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
        default=2,
        help=(
            "并发跑 example (agent) 的最大数 (默认 2)。"
            " researcher_agent 走真实 tavily + 多次 summarize, 比 scoping 重得多; "
            "若 tavily / judge / LangSmith 上游不稳定或限流, 请降到 1。"
        ),
    )
    parser.add_argument(
        "--judge-concurrency",
        type=int,
        default=2,
        help=(
            "judge LLM 调用的全局并发上限 (默认 2)。与 --max-concurrency (agent/example 并发) 解耦: "
            "agent 可高并发跑搜索, judge 调用受此更低上限约束, 避免多个 example 同时判分打爆 gateway。"
        ),
    )
    parser.add_argument(
        "--judge-role",
        default="JUDGE",
        help=(
            "判定研究输出质量的 judge 模型角色 (默认 JUDGE, 即用 .env 里的 JUDGE_MODEL)。"
            " RESEARCHER_MODEL 若指向 qwen 等不支持 enable_thinking 参数的端点, judge 会无法产出 feedback;"
            " 默认走 JUDGE_MODEL 避免该坑. 想让 judge 复用 researcher 模型: --judge-role RESEARCHER"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    global _JUDGE_ROLE, _JUDGE_SEMAPHORE
    _JUDGE_ROLE = args.judge_role
    _JUDGE_SEMAPHORE = threading.BoundedSemaphore(args.judge_concurrency)

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
            f"请先运行: python -m scripts.research_agent.upload_research_dataset",
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
    print(f"agent 并发: {args.max_concurrency}")
    print(f"judge 并发: {args.judge_concurrency}")
    print()

    result = client.evaluate(
        target_func,
        data=data,
        evaluators=[evaluate_criteria_coverage, evaluate_citation_grounding],
        experiment_prefix=args.experiment_prefix,
        max_concurrency=args.max_concurrency,
        # 单条 example 失败 (如 tavily 偶发空响应 / 上游 5xx 重试耗尽) 只 log 不中断,
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
