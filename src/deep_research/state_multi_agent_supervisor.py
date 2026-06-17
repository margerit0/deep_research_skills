
"""
多智能体研究监督者 (Multi-Agent Research Supervisor) 的状态定义。

本模块定义了多智能体研究监督者工作流所使用的状态对象与工具，
涵盖了协调状态 (coordination state) 以及研究工具。
"""

import operator
from typing_extensions import Annotated, TypedDict, Sequence

from langchain_core.messages import BaseMessage
from langchain_core.tools import tool
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

class SupervisorState(TypedDict):
    """
    多智能体研究监督者的状态。

    负责管理监督者与研究智能体之间的协调，追踪研究进展，
    并累积来自多个子智能体的研究发现。
    """

    # 与监督者 (Supervisor) 交互以进行协调与决策的对话消息记录
    supervisor_messages: Annotated[Sequence[BaseMessage], add_messages]
    # 指引整体研究方向的详细研究简报 (Research brief)
    research_brief: str
    # 经过清洗与结构化处理，可直接用于生成最终报告的研究笔记
    notes: Annotated[list[str], operator.add] = []
    # 用于追踪已执行研究迭代次数的计数器
    research_iterations: int = 0
    # 在子智能体研究过程中收集的、未经处理的原始研究笔记
    raw_notes: Annotated[list[str], operator.add] = []

@tool
class ConductResearch(BaseModel):
    """用于将研究任务委派给专业子智能体的工具。"""
    research_topic: str = Field(
        description="The topic to research. Should be a single topic, and should be described in high detail (at least a paragraph).",
    )

@tool
class ResearchComplete(BaseModel):
    """用于标示研究流程已经完成的工具。"""
    pass
