
"""
研究智能体 (Research Agent) 的状态定义与 Pydantic 数据模式

本模块定义了研究智能体工作流所使用的状态对象与结构化输出模式，
涵盖了研究员的状态管理机制以及标准化的输出格式。
"""

import operator
from typing_extensions import TypedDict, Annotated, List, Sequence
from pydantic import BaseModel, Field
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

# ===== 状态定义 (STATE DEFINITIONS) =====

class ResearcherState(TypedDict):
    """
    研究智能体的状态，包含消息历史与研究元数据。

    该状态跟踪研究员的对话记录、用于限制工具调用次数的迭代计数、
    当前正在调查的研究主题、压缩后的研究发现，
    以及用于详细分析的原始研究笔记。
    """
    researcher_messages: Annotated[Sequence[BaseMessage], add_messages]
    tool_call_iterations: int
    research_topic: str
    compressed_research: str
    raw_notes: Annotated[List[str], operator.add]

class ResearcherOutputState(TypedDict):
    """
    研究智能体的输出状态，包含最终研究结果。

    表示研究流程的最终输出，包含压缩后的研究发现
    以及研究过程中产生的全部原始笔记。
    """
    compressed_research: str
    raw_notes: Annotated[List[str], operator.add]
    researcher_messages: Annotated[Sequence[BaseMessage], add_messages]

# ===== 结构化输出模式 (STRUCTURED OUTPUT SCHEMAS) =====

class ClarifyWithUser(BaseModel):
    """用于在范围界定阶段决定是否向用户澄清需求的输出模式。"""
    need_clarification: bool = Field(
        description="Whether the user needs to be asked a clarifying question.",
    )
    question: str = Field(
        description="A question to ask the user to clarify the report scope",
    )
    verification: str = Field(
        description="Verify message that we will start research after the user has provided the necessary information.",
    )

class ResearchQuestion(BaseModel):
    """用于生成研究简报 (Research brief) 的输出模式。"""
    research_brief: str = Field(
        description="A research question that will be used to guide the research.",
    )

class Summary(BaseModel):
    """用于网页内容摘要的输出模式。"""
    summary: str = Field(description="Concise summary of the webpage content")
    key_excerpts: str = Field(description="Important quotes and excerpts from the content")
