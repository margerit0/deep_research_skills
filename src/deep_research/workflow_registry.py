"""Describe supported workflow nodes without loading their implementations."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from deep_research.workflow_definition import (
    MODEL_ROLES,
    EdgeDefinition,
    Identifier,
    ModelRole,
    NodeDefinition,
    NodeId,
    PositiveVersion,
    VersionOne,
    WireModel,
    WorkflowCompatibility,
    WorkflowDefinition,
    WorkflowDocument,
)

REGISTRY_VERSION = 1
COMPATIBILITY = WorkflowCompatibility(
    compiler_version=1,
    node_registry_version=REGISTRY_VERSION,
    state_schema_version=1,
)
SAFE_NODE_TYPES = frozenset(
    {
        "clarify_with_user",
        "write_research_brief",
        "final_report_generation",
    }
)
WORKFLOW_CHECKPOINT_FIELDS = ("workflow_binding", "organized_notes")


class EmptyParameters(WireModel):
    """Disallow arbitrary models, prompts, tools or code on core nodes."""


class ProcessingParameters(WireModel):
    """Treat requirements as literal text, never as a template expression."""

    instructions: str = Field(
        min_length=1,
        max_length=4000,
        pattern=r"\S",
        title="处理要求",
        description="作为纯文本处理要求使用，不执行模板变量、表达式或代码。",
    )


class NodeTypeDescription(WireModel):
    """Expose safe editor metadata and the normal-route/state contract."""

    type: NodeId
    type_version: PositiveVersion = 1
    label: str
    kind: Literal["system", "core", "extension"]
    min_instances: int = Field(ge=0, le=1)
    max_instances: int | None = Field(ge=1, le=30)
    fixed_id: NodeId | None
    input_label: str | None
    output_label: str | None
    successor_types: list[NodeId]
    model_roles: list[ModelRole]
    parameter_fields: list[Literal["instructions"]]
    parameters_schema: dict
    default_parameters: dict
    state_reads: list[Identifier]
    state_writes: dict[str, Literal["replace", "overwrite", "merge_messages"]]
    outcomes: list[Literal["continue", "awaiting_input", "failed", "partial"]]
    safe_recovery: bool


class WorkflowNodeCatalog(WireModel):
    """Version the node directory independently of any execution capability."""

    schema_version: VersionOne = 1
    registry_version: PositiveVersion = REGISTRY_VERSION
    node_types: list[NodeTypeDescription]


def _describe(
    node_type,
    label,
    *,
    kind="core",
    required=True,
    input_label=None,
    output_label=None,
    successors=(),
    roles=(),
    reads=(),
    writes=None,
    outcomes=("continue", "failed"),
    instructions=None,
):
    extension = kind == "extension"
    parameters = ProcessingParameters if extension else EmptyParameters
    return NodeTypeDescription(
        type=node_type,
        label=label,
        kind=kind,
        min_instances=int(required),
        max_instances=None if extension else 1,
        fixed_id=None if extension else node_type,
        input_label=input_label,
        output_label=output_label,
        successor_types=list(successors),
        model_roles=list(roles),
        parameter_fields=["instructions"] if extension else [],
        parameters_schema=parameters.model_json_schema(),
        default_parameters={"instructions": instructions} if extension else {},
        state_reads=list(reads),
        state_writes=writes or {},
        outcomes=list(outcomes),
        safe_recovery=node_type in SAFE_NODE_TYPES,
    )


_FAILURE_WRITES = {
    "research_status": "replace",
    "final_report": "replace",
    "report_research_id": "replace",
    "research_errors": "replace",
}
_NODE_TYPES = (
    _describe(
        "start",
        "开始",
        kind="system",
        output_label="研究问题",
        successors=("prepare_research",),
        outcomes=("continue",),
    ),
    _describe(
        "prepare_research",
        "研究初始化",
        kind="system",
        input_label="研究问题",
        output_label="本轮研究上下文",
        successors=("clarify_with_user", "write_research_brief"),
        reads=(
            "messages",
            "research_id",
            "turn_id",
            "active_research_id",
            "active_turn_id",
            "research_status",
        ),
        writes={
            **dict.fromkeys(
                (
                    "active_research_id",
                    "active_turn_id",
                    "research_status",
                    "research_phase",
                    "effective_config",
                    "research_brief",
                    "user_requirements",
                    "research_constraints",
                    "final_report",
                    "report_research_id",
                    "report_run_id",
                    "report_turn_id",
                    "report_attempt_id",
                    "report_writing_attempt_id",
                    "research_iterations",
                    "supervisor_status",
                    "research_errors",
                    "sources",
                    "source_evidence",
                    "report_reviews",
                    "research_events",
                    "organized_notes",
                ),
                "replace",
            ),
            **dict.fromkeys(
                ("messages", "notes", "raw_notes", "supervisor_messages"), "overwrite"
            ),
        },
    ),
    _describe(
        "clarify_with_user",
        "澄清需求",
        required=False,
        input_label="研究问题与补充回答",
        output_label="明确的研究要求",
        successors=("write_research_brief",),
        roles=("SCOPING",),
        reads=("messages", "research_errors"),
        writes={
            **_FAILURE_WRITES,
            "messages": "merge_messages",
            "research_phase": "replace",
        },
        outcomes=("continue", "awaiting_input", "failed"),
    ),
    _describe(
        "write_research_brief",
        "研究简报",
        input_label="明确的研究要求",
        output_label="研究简报",
        successors=("optimize_plan", "supervisor_subgraph"),
        roles=("SCOPING",),
        reads=("messages", "research_errors"),
        writes={
            **_FAILURE_WRITES,
            "research_brief": "replace",
            "research_phase": "replace",
            "supervisor_messages": "overwrite",
            "user_requirements": "replace",
            "research_constraints": "replace",
        },
    ),
    _describe(
        "optimize_plan",
        "研究计划优化",
        kind="extension",
        required=False,
        input_label="研究简报",
        output_label="优化后的研究简报",
        successors=("optimize_plan", "supervisor_subgraph"),
        roles=("SCOPING",),
        reads=("research_brief", "user_requirements", "research_constraints"),
        writes={"research_brief": "replace", "supervisor_messages": "overwrite"},
        instructions="补充研究维度与验证路径，保留用户原始要求，标明待验证的信息。",
    ),
    _describe(
        "supervisor_subgraph",
        "研究协调子流程",
        input_label="研究简报",
        output_label="有效研究笔记与来源",
        successors=("organize_notes", "final_report_generation"),
        roles=("SUPERVISOR", "RESEARCHER", "SUMMARIZATION", "COMPRESSION"),
        reads=(
            "research_brief",
            "supervisor_messages",
            "user_requirements",
            "research_constraints",
            "research_errors",
        ),
        writes={
            **_FAILURE_WRITES,
            **dict.fromkeys(("notes", "raw_notes", "supervisor_messages"), "overwrite"),
            **dict.fromkeys(
                (
                    "research_events",
                    "research_iterations",
                    "sources",
                    "source_evidence",
                    "supervisor_status",
                    "research_phase",
                ),
                "replace",
            ),
        },
    ),
    _describe(
        "organize_notes",
        "材料整理",
        kind="extension",
        required=False,
        input_label="有效研究笔记与来源",
        output_label="整理后的材料",
        successors=("organize_notes", "final_report_generation"),
        roles=("COMPRESSION",),
        reads=(
            "notes",
            "organized_notes",
            "sources",
            "source_evidence",
            "research_brief",
        ),
        writes={"organized_notes": "replace"},
        instructions="按研究主题整理已有有效笔记，保留不同观点和来源定位，不生成新的检索来源。",
    ),
    _describe(
        "final_report_generation",
        "最终报告",
        input_label="有效研究材料",
        output_label="含来源引用的研究报告",
        successors=("end",),
        roles=("FINAL_REPORT",),
        reads=(
            "notes",
            "organized_notes",
            "sources",
            "source_evidence",
            "research_brief",
            "user_requirements",
            "research_constraints",
            "research_errors",
            "active_research_id",
        ),
        writes={
            **_FAILURE_WRITES,
            **dict.fromkeys(
                (
                    "research_phase",
                    "report_reviews",
                    "report_run_id",
                    "report_turn_id",
                    "report_attempt_id",
                    "report_writing_attempt_id",
                ),
                "replace",
            ),
        },
        outcomes=("continue", "failed", "partial"),
    ),
    _describe(
        "end",
        "结束",
        kind="system",
        input_label="本轮研究成果",
        outcomes=("continue",),
    ),
)


def node_catalog() -> WorkflowNodeCatalog:
    """Return independent descriptions so clients cannot mutate the registry."""
    return WorkflowNodeCatalog(
        node_types=[item.model_copy(deep=True) for item in _NODE_TYPES]
    )


def node_types() -> dict[str, NodeTypeDescription]:
    """Index a fresh directory by stable type name."""
    return {item.type: item for item in node_catalog().node_types}


def parameters_model(node_type: str) -> type[WireModel]:
    """Select a parameter schema without resolving a graph handler."""
    return (
        ProcessingParameters
        if node_type in {"optimize_plan", "organize_notes"}
        else EmptyParameters
    )


def standard_document(name: str = "标准深度研究") -> WorkflowDocument:
    """Create the seven-node baseline with optional clarification included."""
    baseline = [item for item in _NODE_TYPES if item.kind != "extension"]
    nodes = [NodeDefinition(id=item.type, type=item.type) for item in baseline]
    edges = [
        EdgeDefinition(id=f"edge_{index + 1}", source=before.id, target=after.id)
        for index, (before, after) in enumerate(zip(nodes, nodes[1:]))
    ]
    return WorkflowDocument(
        name=name, definition=WorkflowDefinition(nodes=nodes, edges=edges)
    )


assert set(role for node in _NODE_TYPES for role in node.model_roles) == set(
    MODEL_ROLES
)
