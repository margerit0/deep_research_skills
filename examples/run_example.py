"""端到端跑一遍完整研究流水线, 并把报告 + **完整决策轨迹**存成 Markdown。

这是仓库的「示例」入口: 喂一段研究简报, 走完 `research_agent_full` 的
Scope（澄清→简报）→ Supervisor 派发子课题 → 研究员检索 → 汇总成文,
然后把最终报告连同流水线里**每个 agent 的每一步决策**一起落盘:

- Scope:      澄清判断 + 生成的研究简报
- Supervisor: 每一轮的反思(think_tool)、派发了哪些子课题(并行/单线)、何时判定完成
- 每个研究员:  负责的子课题、加载了哪个 skill、搜了哪些 query、反思、压缩出的发现

实现方式: 用 ``agent.astream_events`` 消费事件流。研究员跑在 supervisor 节点内部的
嵌套 ainvoke 里, 但事件会带着完整的 ``parent_ids``(root→直接父)冒泡上来, 因此可以:
  - 按「哪个研究员子图的 run_id 出现在该工具调用的 parent_ids 里」把工具调用准确归到
    对应研究员(并行时也不串)；
  - 从研究员子图的 *输入* 拿到它负责的 research_topic, 从 *输出* 拿到 compressed_research。

用法::

    cd deep_research_skills
    uv run python examples/run_example.py --slug deepseek-360
    uv run python examples/run_example.py --slug iceland-self-drive
    uv run python examples/run_example.py --slug my-topic --title "我的主题" --brief "……"

依赖与配置同主项目: `.env` 需配好各角色模型与 `TAVILY_API_KEY`; 建议设 `AGENT_RPM`。
注意网关在突发负载下会硬限流, **多个示例请串行跑, 不要并发**。
"""

from __future__ import annotations

# 必须在导入本包任何模块之前加载 .env —— model_config 在 import 期就会读取环境变量。
from dotenv import load_dotenv

load_dotenv()

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage


# ============================================================
# 内置示例注册表: slug -> (标题, 研究简报)
# ============================================================

EXAMPLES: dict[str, dict[str, str]] = {
    # 跨领域综合调研 —— 围绕一家公司的多面调研。主管常会按「人物/时间线/对比」
    # 拆成多个子课题并行(也可能判定整体性强而单线), 是观察调度决策的好例子。
    "deepseek-360": {
        "title": "DeepSeek 360° 全景调研",
        "brief": (
            "我想全面了解 DeepSeek（深度求索）这家中国 AI 公司，请从四个方面展开："
            "(1) 创始人梁文锋及核心团队的背景，以及与幻方量化（High-Flyer）的渊源；"
            "(2) DeepSeek 从成立至今的关键模型发布时间线与重要节点"
            "（例如 DeepSeek V2、V3、R1 等里程碑及其发布时间）；"
            "(3) DeepSeek 的主力模型与其他主流开源/闭源大模型在能力定位上的对比"
            "（侧重定位、特点与适用场景，不必精确到价格）；"
            "(4) DeepSeek 在模型架构与训练方法上的代表性技术贡献"
            "（例如 MoE 架构、MLA 多头潜在注意力、R1 的强化学习训练等），"
            "并尽量给出可追溯的论文或官方来源。"
        ),
    },
    # 生活决策类 —— 整体性强的规划题, 主管通常单线深委派, 展示研究员的检索-反思循环。
    "iceland-self-drive": {
        "title": "冰岛自驾环岛 8 天行程规划",
        "brief": (
            "我和伴侣计划 2026 年 9 月到 10 月第一次去冰岛自驾环岛，行程 8 天，"
            "预算中等偏上。请帮我规划："
            "(1) 沿 1 号环岛公路（Ring Road）的分段行程安排与每天大致驻地；"
            "(2) 必看的自然景观（例如黄金圈、南岸瀑布群、杰古沙龙冰川湖、东部峡湾等）"
            "的具体位置与建议游览时长；"
            "(3) 自驾相关的实用注意事项（车型选择、9–10 月的路况与天气、加油与限速规则等）；"
            "(4) 沿途各段推荐的住宿区域与大致预算区间。"
        ),
    },
}


# ============================================================
# 事件流捕获 —— 从 astream_events 还原每个 agent 的决策
# ============================================================

class EventCapture:
    """消费 ``agent.astream_events`` 的事件, 重建流水线全过程。

    关键字段:
      - tool_events:        每次工具调用 {run_id, parent_ids, name, args}
      - researcher_topics:  研究员子图 run_id -> 它负责的 research_topic(来自子图输入)
      - supervisor_messages/research_brief/final_report/messages: 取自各节点 on_chain_end 输出
    """

    def __init__(self) -> None:
        self.tool_events: list[dict] = []
        self.researcher_topics: dict[Any, str] = {}
        self.supervisor_messages: list = []
        self.messages: list = []
        self.research_brief: str = ""
        self.final_report: str = ""
        self.root_run_id: Any = None

    @staticmethod
    def _unwrap_args(raw: Any) -> dict:
        if isinstance(raw, dict):
            # 某些版本把输入再包一层 {"input": {...}}
            if set(raw.keys()) == {"input"} and isinstance(raw["input"], dict):
                return raw["input"]
            return raw
        return {"_": raw}

    async def run(self, agent, payload: dict, config: dict) -> dict:
        root_output: dict = {}
        async for ev in agent.astream_events(payload, config=config):
            et = ev.get("event")
            data = ev.get("data") or {}

            if et == "on_chain_start":
                if self.root_run_id is None and not (ev.get("parent_ids") or []):
                    self.root_run_id = ev.get("run_id")
                inp = data.get("input")
                # 研究员子图的输入带 research_topic —— 记下 run_id 与它负责的子课题
                if isinstance(inp, dict) and inp.get("research_topic"):
                    self.researcher_topics[ev.get("run_id")] = str(inp["research_topic"])

            elif et == "on_tool_start":
                self.tool_events.append({
                    "run_id": ev.get("run_id"),
                    "parent_ids": list(ev.get("parent_ids") or []),
                    "name": ev.get("name"),
                    "args": self._unwrap_args(data.get("input")),
                })

            elif et == "on_chain_end":
                out = data.get("output")
                if not isinstance(out, dict):
                    continue
                # 取各字段「最丰富」的一份 (节点名在嵌套图里不一定可靠, 按内容兜底)
                if out.get("final_report"):
                    self.final_report = str(out["final_report"])
                if out.get("research_brief"):
                    self.research_brief = str(out["research_brief"])
                sm = out.get("supervisor_messages")
                if isinstance(sm, list) and len(sm) > len(self.supervisor_messages):
                    self.supervisor_messages = sm
                msgs = out.get("messages")
                if isinstance(msgs, list) and len(msgs) > len(self.messages):
                    self.messages = msgs
                if not (ev.get("parent_ids") or []):
                    root_output = out
        # root 输出兜底补齐
        for key, attr in (("final_report", "final_report"), ("research_brief", "research_brief")):
            if not getattr(self, attr) and root_output.get(key):
                setattr(self, attr, str(root_output[key]))
        return root_output

    # ---- 分析 ----

    def researcher_records(self) -> list[dict]:
        """每个研究员一条: {topic, tools(按序)}, 按首个工具出现顺序。

        归属规则: 研究员子图的内部节点(llm_call/tool_node/...)输入里也带 research_topic,
        所以一个工具调用的「真正研究员」= 它 parent_ids(root→直接父) 里**最浅**的那个
        带 research_topic 的 run —— 即研究员子图本身, 而非其内部某个节点。
        """
        topic_runs = set(self.researcher_topics)
        groups: dict[Any, list[dict]] = {}
        order: list[Any] = []
        for ev in self.tool_events:
            key = next((pid for pid in ev["parent_ids"] if pid in topic_runs), None)
            if key is None:
                continue
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(ev)

        return [
            {"topic": self.researcher_topics.get(key, ""), "tools": groups[key]}
            for key in order
        ]


# ============================================================
# 渲染辅助
# ============================================================

def _fmt_tool_decision(ev: dict) -> str | None:
    name = ev.get("name")
    args = ev.get("args") or {}
    if name == "load_skill":
        return f"📚 加载 skill：`{args.get('skill_name', '?')}`"
    if name == "tavily_search":
        return f"🔍 搜索：{args.get('query', '?')}"
    if name == "think_tool":
        reflection = str(args.get("reflection", "")).strip().replace("\n", " ")
        if len(reflection) > 400:
            reflection = reflection[:400] + "……"
        return f"🤔 反思：{reflection}"
    return None


def _supervisor_decision_lines(supervisor_messages: list) -> list[str]:
    """把 supervisor 的每一轮决策(反思/派发/完成)渲染成有序列表。"""
    lines: list[str] = []
    round_no = 0
    for msg in supervisor_messages or []:
        tool_calls = getattr(msg, "tool_calls", None) or []
        if not tool_calls:
            continue
        round_no += 1
        conducts = [c for c in tool_calls if c.get("name") == "ConductResearch"]
        thinks = [c for c in tool_calls if c.get("name") == "think_tool"]
        completes = [c for c in tool_calls if c.get("name") == "ResearchComplete"]
        lines.append(f"**第 {round_no} 轮决策**")
        for c in thinks:
            reflection = str((c.get("args") or {}).get("reflection", "")).strip().replace("\n", " ")
            if len(reflection) > 500:
                reflection = reflection[:500] + "……"
            lines.append(f"- 🤔 反思：{reflection}")
        if conducts:
            verb = "并行派发" if len(conducts) > 1 else "派发"
            lines.append(f"- 📤 **{verb} {len(conducts)} 个子课题**：")
            for i, c in enumerate(conducts, 1):
                topic = str((c.get("args") or {}).get("research_topic", "")).strip()
                head = topic.split("\n", 1)[0]
                if len(head) > 160:
                    head = head[:160] + "……"
                lines.append(f"    {i}. {head}")
        if completes:
            lines.append("- ✅ 判定研究完成，进入成文阶段")
        lines.append("")
    return lines


# ============================================================
# 运行 + 渲染
# ============================================================

async def run_pipeline(brief: str) -> EventCapture:
    """跑完整流水线; 若 Scope 反问澄清则补一句确认后重跑一次。返回事件捕获。"""
    from deep_research.research_agent_full import agent

    cap = EventCapture()
    config = {"recursion_limit": 100}
    await cap.run(agent, {"messages": [HumanMessage(content=brief)]}, config)

    # Scope 判定需要澄清时, 图会在 clarify_with_user 直接 END, 没有 final_report。
    if not cap.final_report:
        prior = list(cap.messages or [])
        if prior and isinstance(prior[-1], AIMessage):
            print("Scope 提出了澄清问题, 自动确认后重跑……", file=sys.stderr)
            prior.append(
                HumanMessage(content="以上信息已足够，请直接基于这些信息开始研究，不要再追问。")
            )
            cap = EventCapture()
            await cap.run(agent, {"messages": prior}, config)

    return cap


def render_markdown(title: str, brief: str, cap: EventCapture) -> str:
    from deep_research.utils import get_today_str

    records = cap.researcher_records()
    subtopic_count = sum(
        len([c for c in (getattr(m, "tool_calls", None) or []) if c.get("name") == "ConductResearch"])
        for m in cap.supervisor_messages
    )
    parallel = len(records) > 1
    final_report = cap.final_report.strip()

    # Scope 的确认/澄清话术: messages 里第一条非空 AIMessage。
    scope_confirmation = ""
    for m in cap.messages or []:
        if isinstance(m, AIMessage) and isinstance(m.content, str) and m.content.strip():
            scope_confirmation = m.content.strip()
            break

    L: list[str] = []
    L.append(f"# {title}")
    L.append("")
    L.append(
        "> 本文由本仓库的深度研究智能体（`research_agent_full` 全流程）**自动生成**，"
        "正文未经人工编辑，用于展示系统能力。文末附**完整决策轨迹**（每个 agent 的每一步）。"
    )
    L.append(">")
    L.append(f"> 生成日期：{get_today_str()}")
    if parallel:
        L.append(
            f"> · 流水线：Scope（澄清→简报）→ Supervisor 派发 **{subtopic_count}** 个子课题"
            f" → **{len(records)}** 名研究员**并行**检索 → 汇总成文"
        )
    else:
        L.append(
            f"> · 流水线：Scope（澄清→简报）→ Supervisor 派发 **{subtopic_count or 1}** 个子课题"
            f" → 研究员深度检索（检索→反思循环）→ 汇总成文"
        )
    if os.getenv("LANGSMITH_TRACING", "").lower() in {"1", "true", "yes"} and cap.root_run_id:
        proj = os.getenv("LANGSMITH_PROJECT", "(default)")
        L.append(f"> · 完整 trace 已上报 LangSmith 项目 `{proj}`（root run_id `{cap.root_run_id}`）")
    L.append("")

    # ---- 最终报告(主角, 置顶) ----
    L.append("## 📄 最终报告")
    L.append("")
    L.append(final_report if final_report else "_（未生成最终报告）_")
    L.append("")
    L.append("---")
    L.append("")

    # ---- 决策与执行轨迹 ----
    L.append("## 🧭 决策与执行轨迹（流水线全过程）")
    L.append("")
    L.append("### ① Scope · 范围界定")
    L.append("")
    L.append("**用户原始提问**")
    L.append("")
    L.append("> " + brief.replace("\n", "\n> "))
    L.append("")
    if scope_confirmation:
        L.append("**Scope 判断**（确认信息充分，转写研究简报）")
        L.append("")
        L.append("> " + scope_confirmation.replace("\n", "\n> "))
        L.append("")
    if cap.research_brief:
        L.append("**生成的研究简报**（下游 supervisor 的输入）")
        L.append("")
        L.append("> " + cap.research_brief.strip().replace("\n", "\n> "))
        L.append("")

    L.append("### ② Supervisor · 主管调度决策")
    L.append("")
    sup_lines = _supervisor_decision_lines(cap.supervisor_messages)
    L.extend(sup_lines if sup_lines else ["_（无 supervisor 决策记录）_", ""])

    L.append("### ③ Researchers · " + ("研究员并行执行" if parallel else "研究员执行"))
    L.append("")
    if not records:
        L.append("_（未捕获到研究员执行记录）_")
        L.append("")
    for i, rec in enumerate(records, 1):
        head = rec["topic"].split("\n", 1)[0]
        if len(head) > 140:
            head = head[:140] + "……"
        L.append(f"#### 研究员 #{i}" + (f" — 子课题：{head}" if head else ""))
        L.append("")
        for ev in rec["tools"]:
            line = _fmt_tool_decision(ev)
            if line:
                L.append(f"- {line}")
        skills_used = [
            (ev.get("args") or {}).get("skill_name")
            for ev in rec["tools"] if ev.get("name") == "load_skill"
        ]
        skills_used = [s for s in skills_used if s]
        n_search = sum(1 for ev in rec["tools"] if ev.get("name") == "tavily_search")
        L.append("")
        L.append(
            f"> 小结：加载 skill `{', '.join(skills_used) if skills_used else '—'}`，"
            f"执行 {n_search} 次搜索。"
        )
        L.append("")

    return "\n".join(L)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--slug",
        required=True,
        help="示例标识 (输出文件名 examples/<slug>.md); 命中 EXAMPLES 注册表则自动取标题/简报",
    )
    parser.add_argument("--title", help="报告标题 (覆盖注册表)")
    parser.add_argument("--brief", help="研究简报 (覆盖注册表)")
    parser.add_argument("--out", help="输出路径 (默认 examples/<slug>.md, 相对脚本所在目录)")
    return parser.parse_args()


async def amain() -> int:
    args = parse_args()

    preset = EXAMPLES.get(args.slug, {})
    title = args.title or preset.get("title")
    brief = args.brief or preset.get("brief")

    if not brief:
        print(
            f"ERROR: slug '{args.slug}' 不在内置注册表中, 且未提供 --brief。\n"
            f"  可用内置示例: {', '.join(EXAMPLES)}",
            file=sys.stderr,
        )
        return 1
    title = title or args.slug

    out_path = Path(args.out) if args.out else Path(__file__).parent / f"{args.slug}.md"

    print(f"▶ 运行示例 '{args.slug}': {title}", file=sys.stderr)
    print("  走 research_agent_full 全流程, 视主题深度可能耗时数分钟……", file=sys.stderr)

    try:
        cap = await run_pipeline(brief)
    except Exception as exc:  # noqa: BLE001 — 上游网关持续 5xx/超时时优雅退出, 不吐 traceback
        print(
            f"ERROR: 流水线未跑完即失败: {type(exc).__name__}: {exc}\n"
            f"  常见原因: 上游网关持续限流/超时 (429/500/524) 或 Tavily 网关不可用。\n"
            f"  建议: 等网关空闲后重试, 期间不要并发连跑多个示例。未写出文件。",
            file=sys.stderr,
        )
        return 3

    if not cap.final_report:
        print("ERROR: 未拿到 final_report (可能 Scope 仍在追问或上游持续限流)。", file=sys.stderr)
    markdown = render_markdown(title, brief, cap)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")

    records = cap.researcher_records()
    print(
        f"✔ 已写入 {out_path}  (研究员 {len(records)} · 报告 {len(cap.final_report)} 字符)",
        file=sys.stderr,
    )
    return 0 if cap.final_report else 2


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    sys.exit(main())
