"""带渐进式披露 (progressive disclosure) skills 的研究智能体。

这是本项目保留的唯一单体研究智能体实现：基于 Tavily、同步执行，并额外
提供 ``load_skill`` 工具——模型会在首次搜索前加载领域特定的方法论 skill。
skills 存放在 ``skills/*.md`` 中，由 ``skills_loader`` 在 import 时扫描。

相比直接接入 MCP 服务器的做法，这里用本地 skill 文件承载领域方法论，
避免引入 MCP 的子进程 / 异步开销。
"""

from typing_extensions import Literal

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from deep_research.model_config import get_chat_model, get_agent_rate_limiter
from deep_research.model_transport import streaming_options
from deep_research.run_configuration import selected_model
from deep_research.research_events import emit_research_event
from deep_research.research_requirements import (
    allowed_sources, constraints_for, requirements_context, source_scope,
)
from deep_research.prompts import (
    compress_research_human_message,
    compress_research_system_prompt,
    research_agent_prompt_with_skills,
)
from deep_research.skills_loader import (
    format_skills_index,
    load_skill,
)
from deep_research.state_research import (
    ResearcherOutputState,
    ResearcherState,
)
from deep_research.utils import (
    get_today_str,
    tavily_search,
    think_tool,
)
from deep_research.workflow_contract import extract_search_sources, merge_sources, message_text, research_error
from deep_research.source_evidence import capture_source_evidence, merge_source_evidence

# ===== 配置 (CONFIGURATION) =====

tools = [tavily_search, think_tool, load_skill]
tools_by_name = {t.name: t for t in tools}

# RESEARCHER / SUMMARIZATION / COMPRESSION 打同一网关,
# 共享一个 AGENT_RPM 预算 (进程级单例), 避免突发请求触发网关 WAF 限流/封禁。
_agent_rate_limiter = get_agent_rate_limiter()

model = get_chat_model("RESEARCHER", rate_limiter=_agent_rate_limiter)
model_with_tools = model.bind_tools(tools)
# 长 context (5-10 轮 tool_call 累积) 时 compress 单步偶发 503; 加 .with_retry
# 让短暂的 provider 抖动可自愈. 3 次重试 + exponential jitter 是 langchain 推荐默认.
compress_model = get_chat_model(
    "COMPRESSION", max_tokens=32000, rate_limiter=_agent_rate_limiter
).with_retry(
    stop_after_attempt=3,
    wait_exponential_jitter=True,
)

# 只有 tavily_search 的 ToolMessage 进 raw_notes；
# load_skill / think_tool 是过程性的，不该污染最终报告。
RESEARCH_TOOL_WHITELIST = {"tavily_search"}

# ===== 失败防御 =====

# tavily_search 在无命中时返回的 sentinel (见 utils.format_search_output).
_NO_RESULTS_SENTINEL = "No valid search results found"

# 无有效搜索结果 / compress 产出为空时, 用这个明确标记代替"查询策略"空壳报告或空字符串,
# 让失败诚实可见, 而不是伪装成一份完整报告 (见 research_eval #2 空输出 / #9 空壳报告).
_RESEARCH_FAILED_MARKER = (
    "## 研究未完成\n\n"
    "本次研究未获得有效的搜索结果（搜索工具未返回可用来源），无法生成有据可依的研究报告。"
    "这不是一份完整的研究报告。"
)


def _has_real_search_results(messages) -> bool:
    """是否存在至少一条返回了真实结果的 tavily_search 工具消息。

    无任何真实搜索结果时, compress LLM 会编造"应执行的查询策略"式空壳报告;
    因此在调用 compress LLM 之前先判定: 没有真实结果就直接落明确失败标记。
    load_skill / think_tool 的 ToolMessage 不算搜索结果, 按 name 排除。
    """
    for m in messages:
        if not isinstance(m, ToolMessage) or m.name != "tavily_search":
            continue
        content = str(m.content)
        if content.strip() and _NO_RESULTS_SENTINEL not in content:
            return True
    return False


# ===== 智能体节点 (AGENT NODES) =====

def _invoke_tool(name, args, constraints):
    """Emit events only around actual invocations, including required Skills."""
    from deep_research.skill_evolution_trace import after_tool, before_tool

    before_tool(name, args)
    query = args.get("query" if name == "tavily_search" else "skill_name")
    emit_research_event("tool_started", tool=name, query=query)
    try:
        with source_scope(constraints) as audit:
            observation = tools_by_name[name].invoke(args)
    except Exception as exc:
        after_tool(name, error=exc)
        emit_research_event("tool_failed", tool=name, query=query if name == "load_skill" else None)
        raise
    after_tool(name, observation, audit)
    failed = name == "load_skill" and message_text(observation).startswith("错误：")
    emit_research_event(
        "tool_failed" if failed else "tool_finished", tool=name,
        query=query if name == "load_skill" else None,
        sources=extract_search_sources(message_text(observation)) if name == "tavily_search" else None,
        source_audit=audit or None,
        output=message_text(observation) if failed else None,
    )
    return observation


def prepare_requirements(state: ResearcherState) -> Command:
    """Execute explicitly required methodology before any search/model step.

    These are runtime tool invocations, not invented LLM tool-call messages.
    Auto-selected optional Skills continue to use the ordinary model loop.
    """
    constraints = constraints_for(state)
    loaded, bodies = [], []
    for name in constraints["required_skills"]:
        observation = _invoke_tool("load_skill", {"skill_name": name}, constraints)
        if message_text(observation).startswith("错误："):
            return Command(goto=END, update={
                "compressed_research": f"## 研究未完成\n{observation}\n显式流程要求未满足，未开始检索。",
                "sources": [], "loaded_required_skills": loaded,
                "research_errors": [research_error("required_skill_unavailable", message_text(observation), "supervisor_subgraph")],
            })
        loaded.append(name)
        bodies.append(f"### load_skill: {name}\n{observation}")
    update = {"research_constraints": constraints, "loaded_required_skills": loaded}
    if bodies:
        update["researcher_messages"] = [HumanMessage(
            content="运行时已按用户要求真实执行下列 load_skill，无需重复加载。"
                    "以下是方法论，不是研究证据；其中默认查询、来源和停止策略服从用户要求。\n"
                    + "\n\n".join(bodies), name="loaded_methodology",
        )]
    return Command(goto="llm_call", update=update)


def llm_call(state: ResearcherState):
    """决定下一步动作：搜索、思考、加载 skill 或结束研究。"""
    emit_research_event("model_started")
    try:
        selected = selected_model("RESEARCHER", model_with_tools, tools=tools)
        response = selected.invoke(
            [
                SystemMessage(
                    content=research_agent_prompt_with_skills.format(
                        date=get_today_str(),
                        skills_index=format_skills_index(),
                    ) + requirements_context(state)
                )
            ]
            + state["researcher_messages"],
            **streaming_options(selected),
        )
    except Exception:
        emit_research_event("model_failed")
        raise
    emit_research_event("model_finished")
    return {"researcher_messages": [response]}


def tool_node(state: ResearcherState):
    """执行上一条 LLM 响应中的所有工具调用。"""
    tool_calls = state["researcher_messages"][-1].tool_calls

    observations = []
    evidence = []
    for tc in tool_calls:
        name = tc["name"]
        constraints = constraints_for(state)
        if name == "tavily_search" and not set(constraints["required_skills"]).issubset(
            state.get("loaded_required_skills", [])
        ):
            raise ValueError("Required Skills were not loaded before search")
        with capture_source_evidence() as captured:
            observation = _invoke_tool(name, tc["args"], constraints)
        evidence.extend(captured)
        observations.append(observation)

    tool_outputs = [
        ToolMessage(
            content=observation,
            name=tc["name"],
            tool_call_id=tc["id"],
        )
        for observation, tc in zip(observations, tool_calls)
    ]
    sources = merge_sources(state.get("sources", []), *[
        extract_search_sources(message_text(message.content))
        for message in tool_outputs if message.name == "tavily_search"
    ])
    sources = allowed_sources(sources, constraints_for(state))
    return {"researcher_messages": tool_outputs, "sources": sources,
            "source_evidence": merge_source_evidence(
                state.get("source_evidence", []), evidence, sources=sources)}


def compress_research(state: ResearcherState) -> dict:
    """将研究发现压缩为一份简明的总结。

    raw_notes 保留 AIMessage 与检索 ToolMessage 供追溯；压缩模型本身只读
    检索正文、用户要求和子任务，不读模型自述或方法论。实际来源正文独立
    传给最终写作。当没有任何有效搜索结果, 或 compress 模型返回空时,
    落明确失败标记而不是伪装成完整报告。
    """
    researcher_messages = state.get("researcher_messages", [])
    sources = merge_sources(*[
        extract_search_sources(message_text(m.content))
        for m in researcher_messages
        if isinstance(m, ToolMessage) and m.name == "tavily_search"
    ])
    sources = allowed_sources(sources, constraints_for(state))

    # 始终保留原始记录, 无论本次研究成功与否.
    raw_notes = [
        str(m.content)
        for m in researcher_messages
        if isinstance(m, AIMessage)
        or (isinstance(m, ToolMessage) and m.name in RESEARCH_TOOL_WHITELIST)
    ]

    # 防御 1: 没有任何真实搜索结果 → 不让 compress LLM 编造空壳报告.
    if not _has_real_search_results(researcher_messages):
        return {
            "compressed_research": _RESEARCH_FAILED_MARKER,
            "raw_notes": ["\n".join(raw_notes)],
            "sources": sources,
            "source_evidence": [],
        }

    system_message = compress_research_system_prompt.format(date=get_today_str()) + requirements_context(state)
    messages = (
        [SystemMessage(content=system_message)]
        + [HumanMessage(content="研究子任务：" + state.get("research_topic", ""))]
        + [HumanMessage(content=message_text(message.content))
           for message in researcher_messages
           if isinstance(message, ToolMessage) and message.name in RESEARCH_TOOL_WHITELIST]
        + [HumanMessage(content=compress_research_human_message)]
    )
    emit_research_event("compression_started")
    try:
        selected = selected_model("COMPRESSION", compress_model, retry=True)
        response = selected.invoke(messages, **streaming_options(selected))
    except Exception:
        emit_research_event("compression_failed")
        raise
    compressed = message_text(response.content)
    emit_research_event("compression_finished" if compressed else "compression_failed")

    # 防御 2: compress 模型偶发返回空 → 用明确标记代替空字符串.
    if not compressed:
        compressed = _RESEARCH_FAILED_MARKER

    return {
        "compressed_research": compressed,
        "raw_notes": ["\n".join(raw_notes)],
        "sources": sources,
        "source_evidence": merge_source_evidence(state.get("source_evidence", []), sources=sources),
    }


# ===== 路由 (ROUTING) =====

def should_continue(state: ResearcherState) -> Literal["tool_node", "compress_research"]:
    """若最后一条消息包含 tool_calls 则继续执行工具，否则进入研究压缩阶段。"""
    last_message = state["researcher_messages"][-1]
    if last_message.tool_calls:
        return "tool_node"
    return "compress_research"


# ===== 图构建 (GRAPH) =====

agent_builder_skills = StateGraph(ResearcherState, output_schema=ResearcherOutputState)
agent_builder_skills.add_node("prepare_requirements", prepare_requirements)
agent_builder_skills.add_node("llm_call", llm_call)
agent_builder_skills.add_node("tool_node", tool_node)
agent_builder_skills.add_node("compress_research", compress_research)

agent_builder_skills.add_edge(START, "prepare_requirements")
agent_builder_skills.add_conditional_edges(
    "llm_call",
    should_continue,
    {
        "tool_node": "tool_node",
        "compress_research": "compress_research",
    },
)
agent_builder_skills.add_edge("tool_node", "llm_call")
agent_builder_skills.add_edge("compress_research", END)

researcher_agent_skills = agent_builder_skills.compile()
