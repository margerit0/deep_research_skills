
"""研究范围界定 (Research Scoping) 的状态定义与 Pydantic 数据模式。

本模块定义了用于研究智能体界定研究范围工作流的各种状态对象与结构化输出模式，
涵盖了研究员的状态管理机制以及标准化的输出格式。
"""

import operator
from typing_extensions import Optional, Annotated, List, Sequence

from langchain_core.messages import BaseMessage
from langgraph.graph import MessagesState
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

# ===== 状态定义 (STATE DEFINITIONS) =====

class AgentInputState(MessagesState):
    """全局智能体的输入状态 —— 仅包含来自用户输入的对话消息。"""
    pass

class AgentState(MessagesState):
    """
    完整多智能体 (Multi-Agent) 研究系统的核心状态。

    继承自 MessagesState 并扩展了用于多智能体协作与研究统筹的附加字段。
    注意：为了在子图 (subgraphs) 与主工作流之间保持良好的状态管理，
    部分字段在不同的状态类中可能会有重复定义。
    """

    # 基于用户历史对话上下文生成的最终研究简报 (Research brief)
    research_brief: Optional[str]
    # 与监督者 (Supervisor) 智能体交互以进行任务协调的对话消息记录
    supervisor_messages: Annotated[Sequence[BaseMessage], add_messages]
    # 在研究阶段收集的、未经处理的原始研究笔记
    raw_notes: Annotated[list[str], operator.add] = []
    # 经过清洗与结构化处理，可直接用于生成最终报告的研究笔记
    notes: Annotated[list[str], operator.add] = []
    # 最终生成并经过排版的完整研究报告
    final_report: str

# ===== 结构化输出模式 (STRUCTURED OUTPUT SCHEMAS) =====

class ClarifyWithUser(BaseModel):
    """用于决定是否需要向用户澄清需求并生成澄清问题的输出模式。"""

    need_clarification: bool = Field(
        description="指示是否需要向用户提出澄清问题，以进一步明确研究需求（布尔值）。",
    )
    question: str = Field(
        description="向用户提出的具体问题，旨在澄清并界定研究报告的精确范围。",
    )
    verification: str = Field(
        description="确认性话术，向用户表明：在获取上述必要信息后，我们将立即启动深度研究工作。",
    )

class ResearchQuestion(BaseModel):
    """用于生成结构化研究简报的输出模式。"""

    research_brief: str = Field(
        description="核心研究问题或研究简报，该内容将作为后续所有研究动作的根本指南与执行方向。",
    )
