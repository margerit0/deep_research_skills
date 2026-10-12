"""Full graph with a checkpointed lifecycle for research and clarification.

A LangGraph run ending is not proof that research completed. Consumers check
research_status and the active/report research identifiers before showing a report.
"""

import logging
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Overwrite

from deep_research.model_config import get_chat_model, public_model_config
from deep_research.multi_agent_supervisor import supervisor_agent
from deep_research.prompts import final_report_generation_prompt
from deep_research.research_events import capture_research_events
from deep_research.research_agent_scope import (
    clarify_with_user as scope_clarify,
    write_research_brief as scope_brief,
)
from deep_research.state_scope import AgentInputState, AgentState
from deep_research.submission_journal import guard_execution
from deep_research.submission_journal import accepted_configuration
from deep_research.run_configuration import configured_node, selected_model
from deep_research.utils import get_today_str
from deep_research.workflow_contract import (
    is_research_note,
    log_node_failure,
    message_text,
    research_error,
)

logger = logging.getLogger(__name__)
writer_model = get_chat_model("FINAL_REPORT", max_tokens=32000).with_retry(
    stop_after_attempt=3,
    wait_exponential_jitter=True,
)


def _failure(state, node, code, text):
    return {
        "research_status": "failed",
        "final_report": "",
        "report_research_id": "",
        "research_errors": [
            *state.get("research_errors", []),
            research_error(code, text, node),
        ],
    }


def prepare_research(state: AgentState) -> Command:
    """Start a clean batch or continue exactly the pending clarification."""
    guard_execution(state, "prepare_research")
    humans = [m for m in state.get("messages", []) if isinstance(m, HumanMessage)]
    if not humans or not message_text(humans[-1].content):
        return Command(
            goto=END,
            update=_failure(
                state, "clarify_with_user", "empty_input", "请输入研究问题。"
            ),
        )
    turn_id = state.get("turn_id") or humans[-1].id or str(uuid4())
    research_id = state.get("research_id") or (
        state.get("active_research_id")
        if state.get("research_status") == "awaiting_input"
        else str(uuid4())
    )
    # Defense in depth for an intentionally retried, already completed HTTP input.
    # The durable Atlas endpoint also deduplicates before creating any native run.
    if turn_id == state.get("active_turn_id") and state.get("research_status") in {
        "awaiting_input",
        "succeeded",
        "failed",
        "partial",
    }:
        return Command(goto=END)
    same_research = research_id == state.get("active_research_id")
    if same_research and state.get("research_status") != "awaiting_input":
        raise ValueError(
            "Only a pending clarification can continue the same research_id."
        )
    if state.get("turn_id") and humans[-1].id != turn_id:
        raise ValueError("The human message id must match turn_id.")
    update = {
        "active_research_id": research_id,
        "active_turn_id": turn_id,
        "research_status": "running",
        "research_phase": "clarify",
        "effective_config": accepted_configuration() or (state.get("effective_config") if same_research else None) or public_model_config(include_catalog=False),
        "research_brief": "",
        "final_report": "",
        "report_research_id": "",
        "notes": Overwrite([]),
        "raw_notes": Overwrite([]),
        "supervisor_messages": Overwrite([]),
        "research_iterations": 0,
        "supervisor_status": "",
        "research_errors": [],
        "sources": [],
        "research_events": [],
    }
    if not same_research:
        # Prior studies remain in frontend history, not in the next scoping prompt.
        update["messages"] = Overwrite([humans[-1]])
    return Command(goto="clarify_with_user", update=update)


@configured_node
def clarify_with_user(state: AgentState) -> Command:
    """Keep the shared structured-output/Qwen fallback and mark END as waiting."""
    guard_execution(state, "clarify_with_user")
    try:
        result = scope_clarify(state)
        waiting = result.goto == END
        if not result.update["messages"] or not message_text(
            result.update["messages"][0].content
        ):
            raise ValueError("Empty scoping response")
        return Command(
            goto=result.goto,
            update={
                **result.update,
                "research_status": "awaiting_input" if waiting else "running",
                "research_phase": "clarify" if waiting else "brief",
            },
        )
    except Exception as exc:
        log_node_failure(logger, "clarify_with_user", exc)
        return Command(
            goto=END,
            update=_failure(
                state,
                "clarify_with_user",
                "clarification_failed",
                "需求澄清失败，请检查后端模型服务后发起新研究。",
            ),
        )


@configured_node
def write_research_brief(state: AgentState) -> Command:
    """Checkpoint the real brief before entering the research subgraph."""
    guard_execution(state, "write_research_brief")
    try:
        result = scope_brief(state)
        if not result["research_brief"].strip():
            raise ValueError("Empty research brief")
        return Command(
            goto="supervisor_subgraph", update={**result, "research_phase": "research"}
        )
    except Exception as exc:
        log_node_failure(logger, "write_research_brief", exc)
        return Command(
            goto=END,
            update=_failure(
                state,
                "write_research_brief",
                "brief_failed",
                "研究简报生成失败，请检查后端模型服务后发起新研究。",
            ),
        )


@configured_node
async def supervisor_subgraph(state: AgentState) -> Command:
    """Gate writing on actual findings, keeping partial successes visible."""
    guard_execution(state, "supervisor_subgraph")
    with capture_research_events(
        state.get("active_research_id", ""), state.get("active_turn_id", "")
    ) as events:
        try:
            result = await supervisor_agent.ainvoke(
                {
                    "supervisor_messages": state["supervisor_messages"],
                    "research_brief": state["research_brief"],
                    "notes": [],
                    "raw_notes": [],
                    "sources": [],
                    "research_errors": [],
                    "research_iterations": 0,
                    "supervisor_status": "",
                }
            )
        except Exception as exc:
            log_node_failure(logger, "supervisor_subgraph", exc)
            return Command(
                goto=END,
                update={
                    **_failure(
                        state,
                        "supervisor_subgraph",
                        "research_failed",
                        "研究流程异常结束，未生成报告。",
                    ),
                    "research_events": events,
                },
            )
    notes = [note for note in result.get("notes", []) if is_research_note(note)]
    update = {
        "research_events": events,
        "notes": Overwrite(notes),
        "raw_notes": Overwrite(result.get("raw_notes", [])),
        "supervisor_messages": Overwrite(result.get("supervisor_messages", [])),
        "research_iterations": result.get("research_iterations", 0),
        "sources": result.get("sources", []),
        "research_errors": result.get("research_errors", []),
        "supervisor_status": result.get("supervisor_status", "failed"),
    }
    if not notes:
        return Command(
            goto=END,
            update={
                **update,
                **_failure(
                    {**state, "research_errors": update["research_errors"]},
                    "supervisor_subgraph",
                    "no_findings",
                    "未获得有效研究结果，无法生成有依据的报告。",
                ),
            },
        )
    update["research_phase"] = "writing"
    return Command(goto="final_report_generation", update=update)


@configured_node
async def final_report_generation(state: AgentState):
    """Write from valid notes; an empty/failed writer leaves a partial result."""
    guard_execution(state, "final_report_generation")
    notes = [note for note in state.get("notes", []) if is_research_note(note)]
    if not notes:
        return _failure(
            state,
            "final_report_generation",
            "no_findings",
            "没有可用于撰写报告的有效研究结果。",
        )
    errors = list(state.get("research_errors", []))
    if not state.get("sources"):
        errors.append(
            research_error(
                "missing_sources",
                "未取得可回读的检索来源，报告的来源覆盖不完整。",
                "final_report_generation",
            )
        )
    try:
        prompt = final_report_generation_prompt.format(
            research_brief=state.get("research_brief", ""),
            findings="\n".join(notes),
            date=get_today_str(),
        )
        response = await selected_model("FINAL_REPORT", writer_model, retry=True).ainvoke([HumanMessage(content=prompt)])
        report = message_text(response.content)
        if not is_research_note(report):
            raise ValueError("Empty or failed final report")
    except Exception as exc:
        log_node_failure(logger, "final_report_generation", exc)
        return {
            "research_status": "partial",
            "final_report": "",
            "report_research_id": "",
            "research_errors": [
                *errors,
                research_error(
                    "report_failed",
                    "最终报告生成失败；已保留研究笔记和来源。",
                    "final_report_generation",
                ),
            ],
        }
    return {
        "final_report": report,
        "report_research_id": state.get("active_research_id", ""),
        "research_status": "partial"
        if errors or state.get("supervisor_status") != "completed"
        else "succeeded",
        "research_phase": "complete",
        "research_errors": errors,
        "messages": [AIMessage(content=report, name="final_report")],
    }


deep_researcher_builder = StateGraph(AgentState, input_schema=AgentInputState)
deep_researcher_builder.add_node("prepare_research", prepare_research)
deep_researcher_builder.add_node("clarify_with_user", clarify_with_user)
deep_researcher_builder.add_node("write_research_brief", write_research_brief)
deep_researcher_builder.add_node("supervisor_subgraph", supervisor_subgraph)
deep_researcher_builder.add_node("final_report_generation", final_report_generation)
deep_researcher_builder.add_edge(START, "prepare_research")
deep_researcher_builder.add_edge("final_report_generation", END)
agent = deep_researcher_builder.compile()
