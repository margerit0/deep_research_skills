
"""
完整多智能体研究系统 (Full Multi-Agent Research System)

本模块整合了研究系统的所有组件：
- 用户澄清与范围界定
- 研究简报 (Research brief) 生成
- 多智能体研究协调
- 最终报告生成

该系统统筹从用户初始输入到最终报告交付的完整研究工作流。
"""

from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, START, END

from deep_research.utils import get_today_str
from deep_research.prompts import final_report_generation_prompt
from deep_research.state_scope import AgentState, AgentInputState
from deep_research.research_agent_scope import clarify_with_user, write_research_brief
from deep_research.multi_agent_supervisor import supervisor_agent

# ===== 配置 (Config) =====

from deep_research.model_config import get_chat_model
# 最终报告是全流程里最大的单次 LLM 调用 (32k max_tokens + 汇总所有研究发现),
# 长 context 下最易撞网关瞬时 5xx/超时 (如 Cloudflare 524). 与 research_agent_skills
# 里的 compress_model 一致, 加 .with_retry 让短暂抖动自愈, 避免一次超时白跑整条流水线.
writer_model = get_chat_model("FINAL_REPORT", max_tokens=32000).with_retry(
    stop_after_attempt=3,
    wait_exponential_jitter=True,
)

# ===== 最终报告生成 (FINAL REPORT GENERATION) =====

from deep_research.state_scope import AgentState

async def final_report_generation(state: AgentState):
    """
    最终报告生成节点。

    将所有研究发现综合成一份全面的最终报告
    """

    notes = state.get("notes", [])

    findings = "\n".join(notes)

    final_report_prompt = final_report_generation_prompt.format(
        research_brief=state.get("research_brief", ""),
        findings=findings,
        date=get_today_str()
    )

    final_report = await writer_model.ainvoke([HumanMessage(content=final_report_prompt)])

    return {
        "final_report": final_report.content, 
        "messages": ["Here is the final report: " + final_report.content],
    }

# ===== 图构建 (GRAPH CONSTRUCTION) =====
# 构建整体工作流
deep_researcher_builder = StateGraph(AgentState, input_schema=AgentInputState)

# 添加工作流节点
deep_researcher_builder.add_node("clarify_with_user", clarify_with_user)
deep_researcher_builder.add_node("write_research_brief", write_research_brief)
deep_researcher_builder.add_node("supervisor_subgraph", supervisor_agent)
deep_researcher_builder.add_node("final_report_generation", final_report_generation)

# 添加工作流的边
deep_researcher_builder.add_edge(START, "clarify_with_user")
deep_researcher_builder.add_edge("write_research_brief", "supervisor_subgraph")
deep_researcher_builder.add_edge("supervisor_subgraph", "final_report_generation")
deep_researcher_builder.add_edge("final_report_generation", END)

# 编译完整工作流
agent = deep_researcher_builder.compile()
