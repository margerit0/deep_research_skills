
"""多智能体监督者 (Multi-Agent Supervisor)——协调多个专业智能体共同完成研究。

本模块实现了一种监督者模式 (Supervisor Pattern)，其中：
1. 一个监督者 (Supervisor) 智能体负责统筹研究活动并分派任务
2. 多个研究员 (Researcher) 智能体独立处理各自的具体子主题
3. 研究结果经汇总与压缩后用于生成最终报告

监督者通过并行执行研究来提升效率，同时为每个研究主题
维护相互隔离的上下文窗口 (context window)。
"""

import asyncio

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
from deep_research.prompts import lead_researcher_prompt
from deep_research.research_agent_skills import researcher_agent_skills as researcher_agent
from deep_research.state_multi_agent_supervisor import (
    SupervisorState,
    ConductResearch,
    ResearchComplete
)
from deep_research.utils import get_today_str, think_tool

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
    return [tool_msg.content for tool_msg in filter_messages(messages, include_types="tool")]

# ===== 配置 (CONFIGURATION) =====

supervisor_tools = [ConductResearch, ResearchComplete, think_tool]
supervisor_model = get_chat_model("SUPERVISOR")
supervisor_model_with_tools = supervisor_model.bind_tools(supervisor_tools)

# 系统常量
# 单个研究员智能体的最大工具调用迭代次数
# 用于防止无限循环，并控制每个主题的研究深度
max_researcher_iterations = 6 # think_tool 与 ConductResearch 的调用次数之和

# 监督者可同时启动的研究智能体的最大并发数量
# 该值会传入 lead_researcher_prompt，用于限制并行研究任务的数量
max_concurrent_researchers = 3

# ===== 监督者节点 (SUPERVISOR NODES) =====

async def supervisor(state: SupervisorState) -> Command[Literal["supervisor_tools"]]:
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
    response = await supervisor_model_with_tools.ainvoke(messages)

    return Command(
        goto="supervisor_tools",
        update={
            "supervisor_messages": [response],
            "research_iterations": state.get("research_iterations", 0) + 1
        }
    )

async def supervisor_tools(state: SupervisorState) -> Command[Literal["supervisor", "__end__"]]:
    """执行监督者的决策——要么开展研究，要么结束流程。

    负责处理：
    - 执行 think_tool 调用以进行策略性反思
    - 针对不同主题启动并行研究智能体
    - 汇总研究结果
    - 判定研究何时完成

    Args:
        state: 当前监督者状态，包含消息记录与迭代计数

    Returns:
        用于继续监督、结束流程或处理错误的 Command
    """
    supervisor_messages = state.get("supervisor_messages", [])
    research_iterations = state.get("research_iterations", 0)
    most_recent_message = supervisor_messages[-1]

    # 为单一返回点 (single return) 模式初始化变量
    tool_messages = []
    all_raw_notes = []
    next_step = "supervisor"  # 默认的下一步
    should_end = False

    # 首先检查退出条件
    exceeded_iterations = research_iterations >= max_researcher_iterations
    no_tool_calls = not most_recent_message.tool_calls
    research_complete = any(
        tool_call["name"] == "ResearchComplete" 
        for tool_call in most_recent_message.tool_calls
    )

    if exceeded_iterations or no_tool_calls or research_complete:
        should_end = True
        next_step = END

    else:
        # 在决定下一步之前，先把全部工具调用执行完
        try:
            # 将 think_tool 调用与 ConductResearch 调用区分开
            think_tool_calls = [
                tool_call for tool_call in most_recent_message.tool_calls 
                if tool_call["name"] == "think_tool"
            ]

            conduct_research_calls = [
                tool_call for tool_call in most_recent_message.tool_calls 
                if tool_call["name"] == "ConductResearch"
            ]

            # 处理 think_tool 调用（同步执行）
            for tool_call in think_tool_calls:
                observation = think_tool.invoke(tool_call["args"])
                tool_messages.append(
                    ToolMessage(
                        content=observation,
                        name=tool_call["name"],
                        tool_call_id=tool_call["id"]
                    )
                )

            # 处理 ConductResearch 调用（异步执行）
            if conduct_research_calls:
                # 启动并行研究智能体
                coros = [
                    researcher_agent.ainvoke({
                        "researcher_messages": [
                            HumanMessage(content=tool_call["args"]["research_topic"])
                        ],
                        "research_topic": tool_call["args"]["research_topic"]
                    }) 
                    for tool_call in conduct_research_calls
                ]

                # 等待所有研究完成
                tool_results = await asyncio.gather(*coros)

                # 将研究结果格式化为工具消息 (ToolMessage)
                # 每个子智能体在 result["compressed_research"] 中返回压缩后的研究发现
                # 我们把这些压缩研究写入 ToolMessage 的 content，使得监督者
                # 之后可以通过 get_notes_from_tool_calls() 取回这些发现
                research_tool_messages = [
                    ToolMessage(
                        content=result.get("compressed_research", "Error synthesizing research report"),
                        name=tool_call["name"],
                        tool_call_id=tool_call["id"]
                    ) for result, tool_call in zip(tool_results, conduct_research_calls)
                ]

                tool_messages.extend(research_tool_messages)

                # 汇总所有研究产生的原始笔记
                all_raw_notes = [
                    "\n".join(result.get("raw_notes", [])) 
                    for result in tool_results
                ]

        except Exception as e:
            print(f"Error in supervisor tools: {e}")
            should_end = True
            next_step = END

    # 单一返回点，附带相应的状态更新
    if should_end:
        return Command(
            goto=next_step,
            update={
                "notes": get_notes_from_tool_calls(supervisor_messages),
                "research_brief": state.get("research_brief", "")
            }
        )
    else:
        return Command(
            goto=next_step,
            update={
                "supervisor_messages": tool_messages,
                "raw_notes": all_raw_notes
            }
        )

# ===== 图构建 (GRAPH CONSTRUCTION) =====

# 构建监督者图 (supervisor graph)
supervisor_builder = StateGraph(SupervisorState)
supervisor_builder.add_node("supervisor", supervisor)
supervisor_builder.add_node("supervisor_tools", supervisor_tools)
supervisor_builder.add_edge(START, "supervisor")
supervisor_agent = supervisor_builder.compile()
