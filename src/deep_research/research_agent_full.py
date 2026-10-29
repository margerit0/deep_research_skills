"""Full graph with a checkpointed lifecycle for research and clarification.

A LangGraph run ending is not proof that research completed. Consumers check
research_status and the active/report research identifiers before showing a report.
"""

import logging
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Overwrite

from deep_research.model_config import get_chat_model, public_model_config
from deep_research.multi_agent_supervisor import supervisor_agent
from deep_research.prompts import final_report_generation_prompt, evidence_fidelity_instructions
from deep_research.research_events import capture_research_events
from deep_research.research_agent_scope import (
    clarify_with_user as scope_clarify,
    write_research_brief as scope_brief,
)
from deep_research.state_scope import AgentInputState, AgentState
from deep_research.submission_journal import guard_execution
from deep_research.submission_journal import accepted_configuration
from deep_research.run_configuration import configured_node, selected_model
from deep_research.report_streaming import stream_final_report
from deep_research.source_evidence import WRITER_LIMIT, merge_source_evidence, writer_evidence_context
from deep_research.report_review import ReportReviewContext, ReportReviewFormatError, ReportReviewRequestError, decision_claim_checks, review_report, review_record, revision_messages
from deep_research.research_requirements import (
    allowed_sources, constraints_for, report_citations_within_sources,
    requirements_context, resolve_constraints, report_length_guidance, approximate_report_length,
)
from deep_research.utils import get_today_str
from deep_research.workflow_contract import (
    is_research_note,
    log_node_failure,
    message_text,
    research_error,
)

logger = logging.getLogger(__name__)
writer_model = get_chat_model("FINAL_REPORT", max_tokens=32000)


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
        "user_requirements": "",
        "research_constraints": {"required_skills": [], "allowed_source_urls": None},
        "final_report": "",
        "report_research_id": "",
        "notes": Overwrite([]),
        "report_run_id": "",
        "report_turn_id": "",
        "report_attempt_id": "",
        "report_writing_attempt_id": "",
        "raw_notes": Overwrite([]),
        "supervisor_messages": Overwrite([]),
        "research_iterations": 0,
        "supervisor_status": "",
        "research_errors": [],
        "sources": [],
        "source_evidence": [],
        "report_reviews": [],
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
        originals = [message_text(m.content) for m in state.get("messages", [])
                     if isinstance(m, HumanMessage)]
        return Command(
            goto="supervisor_subgraph", update={
                **result, "research_phase": "research",
                "user_requirements": "\n\n".join(originals),
                "research_constraints": resolve_constraints(originals),
            }
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
                    "user_requirements": state.get("user_requirements", ""),
                    "research_constraints": constraints_for(state),
                    "notes": [],
                    "raw_notes": [],
                    "sources": [],
                    "source_evidence": [],
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
        "sources": allowed_sources(result.get("sources", []), constraints_for(state)),
        "source_evidence": merge_source_evidence(result.get("source_evidence", []),
            sources=allowed_sources(result.get("sources", []), constraints_for(state))),
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
    reviews = []
    review_context = ReportReviewContext()
    if not state.get("sources"):
        errors.append(
            research_error(
                "missing_sources",
                "未取得可回读的检索来源，报告的来源覆盖不完整。",
                "final_report_generation",
            )
        )
    try:
        evidence = state.get("source_evidence", [])
        complete_evidence = bool(evidence) and all(
            item["body_kind"] == "raw_content" and not item["truncated"] for item in evidence
        ) and sum(len(item["text"]) for item in evidence) <= WRITER_LIMIT and (
            {item["url"] for item in evidence} == {source["url"] for source in state.get("sources", [])})
        prompt = final_report_generation_prompt.format(
            research_brief=state.get("research_brief", ""),
            findings=("实际来源正文完整附于下方，请直接据此回答研究简报。"
                      if complete_evidence else "\n".join(notes)),
            date=get_today_str(),
        )
        if approximate_report_length(state) is not None:
            prompt = (
                "按系统中的原始要求直接写短报告。事实使用连续编号引用，末尾以 ### 来源"
                "逐行列出编号、标题与实际采用的 URL。不要解释写作过程，不增加用户未要求的维度。\n"
                + ("实际来源正文附于下方。" if complete_evidence
                   else "以下为派生研究笔记，需与附带原文核对：\n" + "\n".join(notes))
            )
        prompt += requirements_context(state)
        prompt += (
            "\n<Accepted sources>\n只有下列实际采用的来源可被引用；不得从记忆补链接、"
            "替换版本路径或把来源中链接的其他页面当作已读证据。\n"
            + "\n".join(source["url"] for source in state.get("sources", []))
            + "\n</Accepted sources>"
        )
        selected_writer = selected_model("FINAL_REPORT", writer_model)
        writing_messages = [SystemMessage(content=(
                "按用户原始要求撰写最终报告，严格遵守其篇幅和比较维度。"
                "研究笔记是派生材料，不是已核验的报告，也不是必须照抄的结构。"
                "优先依据实际来源正文；保留改变结论的条件、例外、测试范围及历史时间属性。"
                "先为各维度分配篇幅，再选择事实；不要逐项复述资料或展开未要求的 API 示例。"
                "短报告每个用户指定维度只写一个短段落，再写一小段条件性建议。"
                "只有用户明确索要实现教程时才列初始化函数、宏或平台构建步骤；"
                "短比较报告不靠这类实现细节证明完整性。只有用户明确研究未来计划时才写版本展望；"
                "当前比较只写已测事实和当前限制。保留用户所问操作所需的名称、例外与风险，每项事实只说一次。"
                "建议明确标为依据证据的推断，交代实质前提和验证方式，不推导来源未给出的普遍禁令或安全保证。"
                "推断与建议明确标注，来源未说明的行为不得补造。"
                "用户问到的操作若缺少参数取值或执行方式的证据，要明确写出这个缺口。"
                "不同接口或指标的检测对象必须分别说明，不能把构建能力、配置、运行状态等合写成同一种检测。"
                "试用建议的前提须包含来源要求的实质安全适配和内部状态审查，不能仅凭声明支持或编译成功；"
                "性能实测与并发正确性测试不能代替这项审查。"
                + decision_claim_checks
                + evidence_fidelity_instructions
                + requirements_context(state)
                + report_length_guidance(state)
            )), HumanMessage(content=prompt + writer_evidence_context(
                state.get("source_evidence", []), state.get("sources", []))
                + report_length_guidance(state))]

        async def check_report(candidate, writing_attempt_id):
            try:
                decision = await review_report(selected_writer, {**state, "_report_review_context": review_context}, candidate)
            except Exception as exc:
                reviews.append(review_record(candidate, writing_attempt_id, {
                    "status": "unavailable", "error_type": type(exc).__name__,
                    **({"diagnostics": exc.diagnostics} if isinstance(exc, (ReportReviewFormatError, ReportReviewRequestError)) else {}),
                }))
                raise
            reviews.append(review_record(candidate, writing_attempt_id, {"status": "completed", **decision}))
            return None if decision["passed"] else revision_messages(writing_messages, candidate, decision, state)

        report, report_identity = await stream_final_report(
            selected_writer, writing_messages, state,
            review=check_report if state.get("source_evidence") else None,
        )
        if not report_citations_within_sources(report, state.get("sources", [])):
            raise ValueError("Report cites a source that was not consumed")
    except Exception as exc:
        log_node_failure(logger, "final_report_generation", exc)
        return {
            "research_status": "partial",
            "final_report": "",
            "report_research_id": "",
            "report_reviews": reviews,
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
        "report_reviews": reviews,
        **report_identity,
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
