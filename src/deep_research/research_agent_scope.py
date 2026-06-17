

"""用于需求澄清与研究简报 (Research brief) 生成的范围界定 (Scoping) 工作流。"""

from datetime import datetime
from typing import cast
from typing_extensions import Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, get_buffer_string
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from deep_research.model_config import get_chat_model
from deep_research.prompts import (
    clarify_with_user_instructions,
    transform_messages_into_research_topic_prompt,
)
from deep_research.state_scope import (
    AgentInputState,
    AgentState,
    ClarifyWithUser,
    ResearchQuestion,
)
from deep_research.structured_output_fallback import (
    invoke_with_structured_output_fallback,
)


def get_today_str() -> str:
    """以跨平台安全的格式返回当前日期。"""
    today = datetime.now()
    return f"{today.strftime('%a %b')} {today.day}, {today.year}"


def _get_message_history(state: AgentState) -> list[BaseMessage]:
    """返回状态中的消息历史；若不存在则返回空列表。"""
    return cast(list[BaseMessage], state.get("messages") or [])


model = get_chat_model("SCOPING")


def clarify_with_user(
    state: AgentState,
) -> Command[Literal["write_research_brief", "__end__"]]:
    """询问模型是否需要用户提供更多澄清信息。"""
    response = invoke_with_structured_output_fallback(
        model,
        ClarifyWithUser,
        clarify_with_user_instructions.format(
            messages=get_buffer_string(messages=_get_message_history(state)),
            date=get_today_str(),
        ),
    )

    if response.need_clarification:
        return cast(
            Command[Literal["write_research_brief", "__end__"]],
            Command(
                goto=END,
                update={"messages": [AIMessage(content=response.question)]},
            ),
        )

    return cast(
        Command[Literal["write_research_brief", "__end__"]],
        Command(
            goto="write_research_brief",
            update={"messages": [AIMessage(content=response.verification)]},
        ),
    )


def write_research_brief(state: AgentState):
    """将对话历史转换为供下游使用的研究简报 (Research brief)。"""
    response = invoke_with_structured_output_fallback(
        model,
        ResearchQuestion,
        transform_messages_into_research_topic_prompt.format(
            messages=get_buffer_string(_get_message_history(state)),
            date=get_today_str(),
        ),
    )

    return {
        "research_brief": response.research_brief,
        "supervisor_messages": [HumanMessage(content=f"{response.research_brief}.")],
    }


deep_researcher_builder = StateGraph(AgentState, input_schema=AgentInputState)
deep_researcher_builder.add_node("clarify_with_user", clarify_with_user)
deep_researcher_builder.add_node("write_research_brief", write_research_brief)
deep_researcher_builder.add_edge(START, "clarify_with_user")
deep_researcher_builder.add_edge("write_research_brief", END)

scope_research = deep_researcher_builder.compile()
