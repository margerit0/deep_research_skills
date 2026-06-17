"""对 deep_research_scoping 数据集运行评估实验, 并把结果上传到 LangSmith。

执行流程:

    1. 实例化 scope agent (复用 src 的 ``scope_research``)
    2. 定义两个 LLM-as-judge 评估器:
       - evaluate_success_criteria: 逐条判断 brief 是否覆盖 ground-truth criteria
       - evaluate_no_assumptions  : 判断 brief 是否引入了用户未提及的假设
    3. 调用 ``langsmith_client.evaluate(...)`` 触发批量评估

实现说明:

    * 模型实例化统一走 ``model_config.get_chat_model(role)``, 跟 src 保持一致;
      因此需要 ``SCOPING_MODEL`` 等环境变量, 不再读 ``OPENAI_AGENT_MODEL``.
    * 通过 CLI 参数 ``--judge-role`` 可让 judge 用与 agent 不同的模型
      (例如 agent 用便宜的, judge 用更强的).

用法::

    cd deep_research_skills
    python -m scripts.run_scoping_eval                          # 跑全量 (10 条)
    python -m scripts.run_scoping_eval --limit 3                # 只跑前 3 条 (快速冒烟)
    python -m scripts.run_scoping_eval --experiment-prefix v2   # 自定义实验名前缀
    python -m scripts.run_scoping_eval --judge-role JUDGE       # judge 用 JUDGE_MODEL 指定的模型

前置条件::

    1. 已通过 ``scripts/upload_scoping_dataset.py`` 创建并上传过数据集
    2. ``.env`` 中已配置 ``LANGSMITH_API_KEY`` 和相应模型的 ``{ROLE}_MODEL`` 等变量
"""

from __future__ import annotations

# IMPORTANT: load_dotenv() 必须在任何 deep_research.* 之前调用,
# 因为 research_agent_scope 在模块导入时就会实例化 model = get_chat_model("SCOPING"),
# 而该调用需要 OPENAI_API_KEY / SCOPING_MODEL 已经在 os.environ 中.
from dotenv import load_dotenv

load_dotenv()

import argparse
import os
import sys
import uuid
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langsmith import Client
from pydantic import BaseModel, Field, ValidationError

from scripts._eval_retry import with_retry
from deep_research.model_config import get_chat_model
from deep_research.prompts import (
    BRIEF_CRITERIA_PROMPT,
    BRIEF_HALLUCINATION_PROMPT,
)
from deep_research.research_agent_scope import scope_research
from deep_research.state_scope import AgentInputState
from deep_research.structured_output_fallback import (
    batch_invoke_with_structured_output_fallback,
    invoke_with_structured_output_fallback,
)


# ============================================================
# 评估器使用的结构化输出 Schema
# ============================================================


class Criteria(BaseModel):
    """单条成功标准 (success criterion) 的评估结果。"""

    criteria_text: str = Field(
        description="被评估的具体成功标准 (例如 '当前年龄为 25 岁')"
    )
    reasoning: str = Field(
        description="详细说明该标准为何被/未被研究简报覆盖, 应包含简报中的具体证据"
    )
    is_captured: bool = Field(
        description="该标准是否被研究简报充分覆盖 (True) 或缺失/不充分 (False)"
    )


class NoAssumptions(BaseModel):
    """判断研究简报是否做出了用户未提及的假设。"""

    no_assumptions: bool = Field(
        description="True 表示简报只用了用户明确给出的信息, False 表示简报引入了额外假设"
    )
    reasoning: str = Field(
        description="详细说明评估理由; 若存在假设需具体指出, 若不存在需明确说明"
    )


# ============================================================
# 评估器函数
# ============================================================

# 由 CLI 参数注入, evaluate_* 通过模块级变量读取,
# 这样既不污染 evaluate_* 的签名 (LangSmith 要求 (outputs, reference_outputs)),
# 又能让 judge 模型可配置.
_JUDGE_ROLE: str = "SCOPING"


def _make_judge_model():
    """按 ``_JUDGE_ROLE`` 实例化 judge LLM。"""
    return get_chat_model(_JUDGE_ROLE)


def evaluate_success_criteria(outputs: dict, reference_outputs: dict) -> dict:
    """逐条 (per criterion) 判断 brief 是否覆盖了 ground-truth criteria。"""
    research_brief = outputs["research_brief"]
    success_criteria = reference_outputs["criteria"]

    model = _make_judge_model()
    responses = cast(
        list[Criteria],
        with_retry(batch_invoke_with_structured_output_fallback)(
            model,
            Criteria,
            [
                BRIEF_CRITERIA_PROMPT.format(
                    research_brief=research_brief,
                    criterion=criterion,
                )
                for criterion in success_criteria
            ],
        ),
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
        "key": "success_criteria_score",
        "score": captured / total if total > 0 else 0.0,
        "comment": f"{captured}/{total} criteria captured",
        # NOTE: 必须用 value 不能用 extra 或 metadata.
        # - metadata: LangSmith SDK 的 Client._log_evaluation_feedback
        #   把 EvaluationResult 转 Feedback 时直接忽略 metadata.
        # - extra: SDK 会传给 create_feedback, 但服务端会强制覆盖为
        #   {"error": False/True}, 用户写入的内容丢失.
        # - value: 是 Feedback 模型里唯一可以承载任意 JSON dict 的字段,
        #   会被服务端如实持久化, fetch 时可通过 fb.value 读回.
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


def evaluate_no_assumptions(outputs: dict, reference_outputs: dict) -> dict:
    """判断 brief 是否引入了用户未明确说过的假设。"""
    research_brief = outputs["research_brief"]
    success_criteria = reference_outputs["criteria"]

    model = _make_judge_model()
    response = cast(
        NoAssumptions,
        with_retry(invoke_with_structured_output_fallback)(
            model,
            NoAssumptions,
            BRIEF_HALLUCINATION_PROMPT.format(
                research_brief=research_brief,
                success_criteria=str(success_criteria),
            ),
        ),
    )

    return {
        "key": "no_assumptions_score",
        "score": bool(response.no_assumptions),
        "comment": response.reasoning,
    }


# ============================================================
# Target function
# ============================================================


def target_func(inputs: dict[str, Any]) -> dict[str, Any]:
    """对单条 example 调用 scope agent, 返回完整 state (含 research_brief)。"""
    config: RunnableConfig = {"configurable": {"thread_id": str(uuid.uuid4())}}
    return cast(
        dict[str, Any],
        with_retry(scope_research.invoke)(
            cast(AgentInputState, inputs), config=config
        ),
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
        default=os.getenv("LANGSMITH_DATASET", "deep_research_scoping"),
        help="LangSmith 数据集名称 (默认 deep_research_scoping)",
    )
    parser.add_argument(
        "--experiment-prefix",
        default="Deep Research Scoping",
        help="实验名称前缀 (默认 'Deep Research Scoping')",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="只评估前 N 条 examples (默认评估全量), 适合快速冒烟",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=1,
        help=(
            "并发跑 example 的最大数 (默认 2)。"
            " 若 SCOPING_MODEL 走的是 Qwen/ModelScope 这类网关, 出现 'invalid choices payload'"
            " 类报错时把这个值调到 1, 通常能消除限流引起的空响应。"
        ),
    )
    parser.add_argument(
        "--judge-role",
        default="SCOPING",
        help=(
            "判定 brief 质量的 judge 模型角色 (默认 SCOPING, 即复用 SCOPING_MODEL)。"
            " 若想让 judge 用更强的模型, 在 .env 里加 JUDGE_MODEL=... 然后传 --judge-role JUDGE"
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
            f"请先运行: python -m scripts.upload_scoping_dataset",
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
        evaluators=[evaluate_success_criteria, evaluate_no_assumptions],
        experiment_prefix=args.experiment_prefix,
        max_concurrency=args.max_concurrency,
        # 单条 example 失败(如 ModelScope 偶发返回空 choices)只 log 不中断,
        # 让批量评估能跑完,失败条目会在 LangSmith UI 上标红供逐条排查.
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
