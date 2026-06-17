"""拉取最近一次 'Deep Research Supervisor' 实验的非满分条目, 输出 JSON 供诊断 agent 使用。

用法::

    cd deep_research_skills
    uv run python -m scripts.supervisor.fetch_last_supervisor_eval                       # 全部 10 条, 打印到 stdout
    uv run python -m scripts.supervisor.fetch_last_supervisor_eval --only-failures       # 只输出非满分条目
    uv run python -m scripts.supervisor.fetch_last_supervisor_eval --out diag.json       # 写文件
    uv run python -m scripts.supervisor.fetch_last_supervisor_eval --project-name <name> # 指定具体实验

输出 JSON 每条包含: example 输入 (research_brief), ground-truth num_expected_threads,
supervisor 实际发出的工具调用与委托的 research_topics,
两项评估的 score 和明细 (并行决策对错 + judge 的委托质量判定),
以及 LangSmith run_id (方便回查 trace)。
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from typing import Any

from dotenv import load_dotenv

load_dotenv()
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from langsmith import Client


def _first_research_brief(inputs: dict[str, Any]) -> str:
    """从 inputs.supervisor_messages[0].content 抽 research_brief 文本.

    LangSmith 反序列化后 messages 可能是 dict 也可能是 BaseMessage 对象;
    两种情况都要兼容.
    """
    msgs = inputs.get("supervisor_messages") or []
    if not msgs:
        return ""
    first = msgs[0]
    if isinstance(first, dict):
        return str(first.get("content", ""))
    return str(getattr(first, "content", first))


def _is_perfect(
    parallelism_score: float | None, delegation_score: float | None
) -> bool:
    return parallelism_score == 1.0 and delegation_score == 1.0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--project-name",
        default=None,
        help="指定实验 project 名 (默认取最近一次以 'Deep Research Supervisor' 开头的)",
    )
    parser.add_argument(
        "--only-failures", action="store_true", help="只输出非满分条目"
    )
    parser.add_argument(
        "--out", default=None, help="写到指定文件 (默认打印到 stdout)"
    )
    args = parser.parse_args()

    api_key = os.getenv("LANGSMITH_API_KEY")
    if not api_key:
        print("ERROR: LANGSMITH_API_KEY 未设置", file=sys.stderr)
        return 1

    client = Client(api_key=api_key)

    if args.project_name:
        proj_name = args.project_name
    else:
        projects = list(client.list_projects(name_contains="Deep Research Supervisor"))
        if not projects:
            print("ERROR: 找不到 'Deep Research Supervisor' 实验", file=sys.stderr)
            return 1
        projects.sort(key=lambda p: p.start_time or 0, reverse=True)
        proj_name = projects[0].name

    print(f"# experiment: {proj_name}", file=sys.stderr)

    runs = list(
        client.list_runs(
            project_name=proj_name,
            is_root=True,
            select=[
                "id",
                "inputs",
                "outputs",
                "error",
                "reference_example_id",
                "start_time",
            ],
        )
    )
    runs.sort(key=lambda r: r.start_time or 0)
    print(f"# total runs: {len(runs)}", file=sys.stderr)

    out_items: list[dict[str, Any]] = []

    for idx, run in enumerate(runs, 1):
        num_expected_threads: int | None = None
        if run.reference_example_id:
            try:
                ex = client.read_example(run.reference_example_id)
                ref = ex.outputs or {}
                if ref.get("num_expected_threads") is not None:
                    num_expected_threads = int(ref["num_expected_threads"])
            except Exception as exc:
                print(
                    f"# WARN: read_example({run.reference_example_id}) failed: {exc}",
                    file=sys.stderr,
                )

        out = run.outputs or {}

        # feedback (评估器打分)
        fbs = list(client.list_feedback(run_ids=[run.id]))
        fb_map = {fb.key: fb for fb in fbs}
        par = fb_map.get("correct_next_step")
        dlg = fb_map.get("delegation_quality_score")
        par_score = par.score if par else None
        dlg_score = dlg.score if dlg else None

        # 并行决策明细存在 fb.value (expected/actual/tool_calls/research_topics)
        par_detail: dict | None = None
        if par and isinstance(par.value, dict):
            par_detail = par.value

        # 委托质量明细存在 fb.value.checks + reasoning
        dlg_checks: dict | None = None
        dlg_reasoning: str | None = None
        if dlg and isinstance(dlg.value, dict):
            dlg_checks = dlg.value.get("checks")
            dlg_reasoning = dlg.value.get("reasoning")

        if args.only_failures and _is_perfect(par_score, dlg_score) and not run.error:
            continue

        item: dict[str, Any] = {
            "index": idx,
            "run_id": str(run.id),
            "example_id": str(run.reference_example_id)
            if run.reference_example_id
            else None,
            "input_research_brief": _first_research_brief(run.inputs or {}),
            "ground_truth_num_expected_threads": num_expected_threads,
            "agent_tool_calls": out.get("tool_calls"),
            "agent_num_conduct_research": out.get("num_conduct_research"),
            "agent_research_topics": out.get("research_topics"),
            "agent_error": run.error,
            "judge_parallelism": {
                "score": par_score,
                "summary": par.comment if par else None,
                "detail": par_detail,
            },
            "judge_delegation_quality": {
                "score": dlg_score,
                "summary": dlg.comment if dlg else None,
                "checks": dlg_checks,
                "reasoning": dlg_reasoning,
            },
        }
        out_items.append(item)

    payload = {
        "experiment": proj_name,
        "total_runs": len(runs),
        "returned": len(out_items),
        "filter": "only_failures" if args.only_failures else "all",
        "items": out_items,
    }

    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"# wrote {len(out_items)} items to {args.out}", file=sys.stderr)
    else:
        print(text)

    return 0


if __name__ == "__main__":
    sys.exit(main())
