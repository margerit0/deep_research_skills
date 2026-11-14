"""Compile a published chain with exactly one route for each business outcome."""

from __future__ import annotations

import logging
import time

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from deep_research.state_scope import AgentInputState, AgentState
from deep_research.submission_journal import guard_execution
from deep_research.workflow_contract import log_node_failure, research_error
from deep_research.workflow_definition import WorkflowBusinessResult
from deep_research.workflow_events import append_event
from deep_research.workflow_nodes import implementations, invoke_business
from deep_research.workflow_validation import WorkflowContractError, normal_successor

logger = logging.getLogger(__name__)


class WorkflowState(AgentState):
    """Add channels only to the workflow graph, preserving old graph checkpoints."""

    workflow_binding: dict
    organized_notes: str | None


def _unavailable(state):
    raise WorkflowContractError("workflow_observation_only")


def compile_workflow(
    document,
    *,
    binding=None,
    handlers=None,
    observe=False,
    verify_entry=None,
    event_sink=append_event,
):
    """Keep observation topology identical while making its handlers nonexecuting."""
    builder = StateGraph(WorkflowState, input_schema=AgentInputState)
    nodes = [
        node for node in document.definition.nodes if node.type not in {"start", "end"}
    ]
    successors = {edge.source: edge.target for edge in document.definition.edges}
    installed = {} if observe else implementations() if handlers is None else handlers

    def adapt(node):
        async def execute(state, config: RunnableConfig):
            if binding is None:
                raise WorkflowContractError("workflow_binding_missing")
            expected = binding.model_dump(mode="json")
            if state.get("workflow_binding") != expected and (
                node.type != "prepare_research" or "workflow_binding" in state
            ):
                raise WorkflowContractError("workflow_binding_mismatch")
            if verify_entry is not None:
                verify_entry(state, config, node)
            guard_execution(state, node.id)
            started = time.monotonic()
            event_sink(config, binding, node, "started", 0)
            try:
                business = await invoke_business(
                    node, state, installed[(node.type, node.type_version)]
                )
                update, result = business.update, business.result
                if node.type == "prepare_research" and result.outcome == "continue":
                    update["workflow_binding"] = expected
                    update["organized_notes"] = None
                    if successors[node.id] == "write_research_brief":
                        update["research_phase"] = "brief"
            except Exception as exc:
                # Ownership/storage checks above must fail closed, never become
                # a successful terminal checkpoint. Business failures are safe.
                log_node_failure(logger, node.id, exc)
                result = WorkflowBusinessResult(outcome="failed")
                update = {
                    "research_status": "failed",
                    "final_report": "",
                    "report_research_id": "",
                    "research_errors": [
                        *state.get("research_errors", []),
                        research_error(
                            "workflow_node_failed",
                            "流程节点执行失败，已保留已确认的研究材料。",
                            node.id,
                        ),
                    ],
                }
            successor = normal_successor(document, node.id, result)
            terminal = successor in (None, "end")
            event_sink(
                config,
                binding,
                node,
                "completed" if result.outcome == "continue" else result.outcome,
                max(0, round((time.monotonic() - started) * 1000)),
                terminal=terminal,
            )
            return Command(update=update, goto=END if terminal else successor)

        return execute

    for node in nodes:
        successor = successors.get(node.id)
        targets = tuple(dict.fromkeys((END if successor == "end" else successor, END)))
        builder.add_node(
            node.id, _unavailable if observe else adapt(node), destinations=targets
        )
    builder.add_edge(START, successors["start"])
    return builder.compile()
