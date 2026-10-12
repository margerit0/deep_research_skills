
"""多智能体监督者 (Multi-Agent Supervisor)——协调多个专业智能体共同完成研究。

本模块实现了一种监督者模式 (Supervisor Pattern)，其中：
1. 一个监督者 (Supervisor) 智能体负责统筹研究活动并分派任务
2. 多个研究员 (Researcher) 智能体独立处理各自的具体子主题
3. 研究结果经汇总与压缩后用于生成最终报告

监督者通过并行执行研究来提升效率，同时为每个研究主题
维护相互隔离的上下文窗口 (context window)。
"""

import asyncio
import logging

from typing_extensions import Literal

from langchain_core.messages import (
    HumanMessage,
    BaseMessage,
    SystemMessage,
    ToolMessage,
    filter_messages
)
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command

from deep_research.model_config import get_chat_model
from deep_research.run_configuration import selected_model
from deep_research.prompts import lead_researcher_prompt
from deep_research.research_events import emit_research_event, researcher_task
from deep_research.research_agent_skills import researcher_agent_skills as researcher_agent
from deep_research.state_multi_agent_supervisor import (
    SupervisorState,
    ConductResearch,
    ResearchComplete
)
from deep_research.utils import get_today_str, think_tool
from deep_research.workflow_contract import is_research_note, merge_sources, message_text, research_error, log_node_failure

logger = logging.getLogger(__name__)

def get_notes_from_tool_calls(messages: list[BaseMessage]) -> list[str]:
    """从监督者消息历史中的 ToolMessage 对象里提取研究笔记。

    本函数用于获取子智能体以 ToolMessage 内容形式返回的压缩研究发现。
    当监督者通过 ConductResearch 工具调用将研究任务委派给子智能体时，
    每个子智能体会把压缩后的研究发现作为 ToolMessage 的 content 返回。
    本函数提取所有此类 ToolMessage 的内容，以汇编成最终的研究笔记。

    Args:
        messages: 监督者对话历史中的消息列表

    Returns:
        从 ToolMessage 对象中提取出的研究笔记字符串列表
    """
    return [
        message_text(m.content)
        for m in filter_messages(messages, include_types="tool")
        if m.name == "ConductResearch" and is_research_note(m.content)
    ]


def _finish(state, messages, errors):
    """Keep successful work, but never turn an empty/failed investigation into success."""
    notes = get_notes_from_tool_calls(messages)
    status = "failed" if not notes else "partial" if errors else "completed"
    if not notes and not errors:
        errors = [research_error("no_research", "未获得有效的研究笔记。", "supervisor_subgraph")]
    return Command(goto=END, update={
        "notes": notes,
        "supervisor_status": status,
        "research_errors": errors,
    })

# ===== 配置 (CONFIGURATION) =====

supervisor_tool_definitions = [ConductResearch, ResearchComplete, think_tool]
supervisor_model = get_chat_model("SUPERVISOR")
supervisor_model_with_tools = supervisor_model.bind_tools(supervisor_tool_definitions)

# 系统常量
# 单个研究员智能体的最大工具调用迭代次数
# 用于防止无限循环，并控制每个主题的研究深度
max_researcher_iterations = 6 # think_tool 与 ConductResearch 的调用次数之和

# 监督者可同时启动的研究智能体的最大并发数量
# 该值会传入 lead_researcher_prompt，用于限制并行研究任务的数量
max_concurrent_researchers = 3

# ===== 监督者节点 (SUPERVISOR NODES) =====

async def supervisor(state: SupervisorState) -> Command[Literal["supervisor_tools", "__end__"]]:
    """统筹协调研究活动。

    分析研究简报 (Research brief) 与当前进展，以决定：
    - 哪些研究主题需要调查
    - 是否进行并行研究
    - 研究何时完成

    Args:
        state: 当前监督者状态，包含消息记录与研究进展

    Returns:
        携带更新后状态、前往 supervisor_tools 节点的 Command
    """
    supervisor_messages = state.get("supervisor_messages", [])

    # 准备包含当前日期与约束条件的系统消息
    system_message = lead_researcher_prompt.format(
        date=get_today_str(), 
        max_concurrent_research_units=max_concurrent_researchers,
        max_researcher_iterations=max_researcher_iterations
    )
    messages = [SystemMessage(content=system_message)] + supervisor_messages

    # 对下一步研究行动做出决策
    try:
        response = await selected_model("SUPERVISOR", supervisor_model_with_tools, tools=supervisor_tool_definitions).ainvoke(messages)
    except Exception as exc:
        log_node_failure(logger, "supervisor", exc)
        errors = [*state.get("research_errors", []), research_error(
            "supervisor_failed", "研究协调器调用失败，已保留此前取得的研究结果。", "supervisor_subgraph"
        )]
        return _finish(state, supervisor_messages, errors)

    return Command(
        goto="supervisor_tools",
        update={
            "supervisor_messages": [response],
            "research_iterations": state.get("research_iterations", 0) + 1
        }
    )

async def supervisor_tools(state: SupervisorState) -> Command[Literal["supervisor", "__end__"]]:
    """Run delegations independently and preserve both successful notes and failures."""
    supervisor_messages = state.get("supervisor_messages", [])
    most_recent_message = supervisor_messages[-1]
    calls = most_recent_message.tool_calls
    errors = list(state.get("research_errors", []))
    completed = any(call["name"] == "ResearchComplete" for call in calls)
    exceeded = state.get("research_iterations", 0) >= max_researcher_iterations
    if completed or not calls or exceeded:
        if exceeded and not completed:
            errors.append(research_error(
                "iteration_limit", "研究达到协调轮次上限，覆盖范围可能不完整。", "supervisor_subgraph"
            ))
        return _finish(state, supervisor_messages, errors)

    tool_messages = []
    all_raw_notes = []
    sources = state.get("sources", [])
    try:
        unknown = [call for call in calls if call["name"] not in {"think_tool", "ConductResearch"}]
        if unknown:
            raise ValueError("Unsupported supervisor tool")
        for call in calls:
            if call["name"] == "think_tool":
                tool_messages.append(ToolMessage(
                    content=think_tool.invoke(call["args"]), name="think_tool", tool_call_id=call["id"]
                ))

        research_calls = [call for call in calls if call["name"] == "ConductResearch"]

        async def investigate(call):
            topic = call["args"]["research_topic"]
            with researcher_task(call["id"], topic, state.get("research_iterations", 1)):
                try:
                    result = await researcher_agent.ainvoke({
                        "researcher_messages": [HumanMessage(content=topic)], "research_topic": topic
                    })
                except Exception:
                    emit_research_event("failed")
                    raise
                content = message_text(result.get("compressed_research"))
                valid = is_research_note(content)
                emit_research_event(
                    "completed" if valid else "failed",
                    sources=result.get("sources", []),
                    output=content if valid else "该任务未返回有效的研究笔记。",
                )
                return result

        # return_exceptions retains successful siblings when one researcher fails.
        results = await asyncio.gather(*[investigate(call) for call in research_calls], return_exceptions=True)
        for call, result in zip(research_calls, results):
            content = message_text(result.get("compressed_research")) if isinstance(result, dict) else ""
            if isinstance(result, dict):
                all_raw_notes.extend(result.get("raw_notes", []))
                sources = merge_sources(sources, result.get("sources", []))
            if not is_research_note(content):
                if isinstance(result, Exception):
                    log_node_failure(logger, "researcher", result)
                errors.append(research_error(
                    "researcher_failed", "一个研究任务未获得有效结果，研究覆盖可能不完整。", "supervisor_subgraph"
                ))
                content = "## 研究未完成\n该任务未返回有效的研究笔记。"
            tool_messages.append(ToolMessage(content=content, name="ConductResearch", tool_call_id=call["id"]))
    except Exception as exc:
        log_node_failure(logger, "supervisor_tools", exc)
        errors.append(research_error("supervisor_tools_failed", "研究工具执行失败。", "supervisor_subgraph"))
        result = _finish(state, [*supervisor_messages, *tool_messages], errors)
        result.update.update({"supervisor_messages": tool_messages, "raw_notes": all_raw_notes, "sources": sources})
        return result

    return Command(goto="supervisor", update={
        "supervisor_messages": tool_messages,
        "raw_notes": all_raw_notes,
        "sources": sources,
        "research_errors": errors,
    })

# ===== 图构建 (GRAPH CONSTRUCTION) =====

# 构建监督者图 (supervisor graph)
supervisor_builder = StateGraph(SupervisorState)
supervisor_builder.add_node("supervisor", supervisor)
supervisor_builder.add_node("supervisor_tools", supervisor_tools)
supervisor_builder.add_edge(START, "supervisor")
supervisor_agent = supervisor_builder.compile()
