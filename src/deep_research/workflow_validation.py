"""Validate saved graph structure and explicit publication context without I/O."""

from __future__ import annotations

import json
from collections import Counter, deque
from dataclasses import dataclass

from pydantic import ValidationError

from deep_research.workflow_definition import (
    MAX_DOCUMENT_BYTES,
    ValidationIssue,
    WorkflowBinding,
    WorkflowBusinessResult,
    WorkflowCompatibility,
    WorkflowDocument,
    WorkflowRef,
    WorkflowRevision,
    WorkflowSelection,
    WorkflowValidation,
    semantic_hash,
)
from deep_research.workflow_registry import COMPATIBILITY, node_types, parameters_model


@dataclass(frozen=True)
class PublicationContext:
    """Require the service to provide real directory and implementation checks.

    Construct this only from server state. Passing a browser's node list here
    cannot establish that handlers or model/Skill revisions are available.
    """

    compatibility: WorkflowCompatibility
    implemented_types: frozenset[str]
    model_revision_ids: frozenset[str]
    skill_names: frozenset[str]
    default_selection: WorkflowSelection


class WorkflowContractError(ValueError):
    """Carry a stable public reason without serializing the offending payload."""

    def __init__(self, reason: str):
        """Keep the same reason available to HTTP and factory adapters."""
        self.reason = reason
        super().__init__(reason)


def _pointer(parts) -> str:
    return (
        "/"
        + "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in parts)
    )[:500]


def validate_document(
    value: object,
    *,
    checked_edit_version: int | None = None,
    context: PublicationContext | None = None,
) -> WorkflowValidation:
    """Return actionable locations; incomplete drafts can still be stored.

    Without PublicationContext this is only a structural preflight. Publication
    additionally checks available implementations and six-role configuration.
    The HTTP adapter must bound the raw request body before decoding JSON.
    """
    if context is not None and checked_edit_version is None:
        raise WorkflowContractError("workflow_edit_version_required")
    issues: list[ValidationIssue] = []

    def issue(code, message, *, node=None, edge=None, field=None):
        issues.append(
            ValidationIssue(
                code=code,
                message=message,
                node_id=node,
                edge_id=edge,
                field=field,
            )
        )

    def finish():
        return WorkflowValidation(
            scope="publication" if context is not None else "structure",
            valid=not issues,
            checked_edit_version=checked_edit_version,
            issues=issues[:100],
            truncated=len(issues) > 100,
        )

    try:
        raw = (
            value.model_dump(mode="json")
            if isinstance(value, WorkflowDocument)
            else value
        )
        size = len(
            json.dumps(
                raw, ensure_ascii=False, allow_nan=False, separators=(",", ":")
            ).encode("utf-8")
        )
    except (TypeError, ValueError, RecursionError):
        issue("schema_invalid", "流程必须使用有限的 JSON 数据。", field="/")
        return finish()
    if size > MAX_DOCUMENT_BYTES:
        issue("document_too_large", "流程内容超过 256 KiB 上限。", field="/")
        return finish()
    try:
        document = WorkflowDocument.model_validate(raw)
    except ValidationError as exc:
        for error in exc.errors(
            include_url=False, include_context=False, include_input=False
        ):
            issue(
                "schema_invalid",
                "字段类型、取值或大小不符合流程协议。",
                field=_pointer(error["loc"]),
            )
        return finish()

    registry = node_types()
    nodes = document.definition.nodes
    edges = document.definition.edges
    by_id = {}
    duplicate_nodes = False
    for index, node in enumerate(nodes):
        prefix = f"/definition/nodes/{index}"
        if node.id in by_id:
            duplicate_nodes = True
            issue(
                "node_id_duplicate",
                "节点标识重复。",
                node=node.id,
                field=f"{prefix}/id",
            )
        by_id[node.id] = node
        description = registry.get(node.type)
        if description is None:
            issue(
                "node_type_unknown",
                "当前服务不支持此节点类型。",
                node=node.id,
                field=f"{prefix}/type",
            )
            continue
        if node.type_version != description.type_version:
            issue(
                "node_type_version_unsupported",
                "节点实现版本不受支持。",
                node=node.id,
                field=f"{prefix}/type_version",
            )
        if description.fixed_id and node.id != description.fixed_id:
            issue(
                "core_node_id",
                "基础节点必须保留稳定运行标识。",
                node=node.id,
                field=f"{prefix}/id",
            )
        if description.kind == "extension" and node.id in registry:
            issue(
                "core_node_id",
                "扩展节点不能占用基础节点或类型的保留标识。",
                node=node.id,
                field=f"{prefix}/id",
            )
        try:
            parameters_model(node.type).model_validate(node.parameters)
        except ValidationError as exc:
            for error in exc.errors(
                include_url=False, include_context=False, include_input=False
            ):
                issue(
                    "node_parameters_invalid",
                    "请按节点要求填写参数，不能添加未开放的参数。",
                    node=node.id,
                    field=_pointer(
                        ("definition", "nodes", index, "parameters", *error["loc"])
                    ),
                )

    counts = Counter(node.type for node in nodes)
    for description in registry.values():
        count = counts[description.type]
        if count < description.min_instances or (
            description.max_instances is not None and count > description.max_instances
        ):
            issue(
                "node_count",
                f"「{description.label}」的数量不符合要求。",
                node=description.fixed_id,
                field="/definition/nodes",
            )

    incoming = {identifier: [] for identifier in by_id}
    outgoing = {identifier: [] for identifier in by_id}
    edge_ids, pairs = set(), set()
    for index, edge in enumerate(edges):
        prefix = f"/definition/edges/{index}"
        if edge.id in edge_ids:
            issue(
                "edge_id_duplicate",
                "连接标识重复。",
                edge=edge.id,
                field=f"{prefix}/id",
            )
        edge_ids.add(edge.id)
        pair = (edge.source, edge.target)
        if pair in pairs:
            issue(
                "edge_duplicate", "同一对端口不能重复连接。", edge=edge.id, field=prefix
            )
        pairs.add(pair)
        if edge.source not in by_id or edge.target not in by_id:
            issue(
                "edge_node_missing",
                "连接引用了不存在的节点。",
                edge=edge.id,
                field=prefix,
            )
            continue
        outgoing[edge.source].append(edge.target)
        incoming[edge.target].append(edge.source)
        source = registry.get(by_id[edge.source].type)
        target = registry.get(by_id[edge.target].type)
        if source and target:
            if source.output_label is None or target.input_label is None:
                issue(
                    "edge_port_invalid",
                    "开始没有输入端口，结束没有输出端口。",
                    edge=edge.id,
                    field=prefix,
                )
            if target.type not in source.successor_types:
                issue(
                    "stage_order_invalid",
                    "连接不符合研究阶段顺序。",
                    edge=edge.id,
                    field=prefix,
                )

    if not duplicate_nodes:
        for index, node in enumerate(nodes):
            if len(incoming[node.id]) != (0 if node.type == "start" else 1):
                issue(
                    "input_count",
                    "除开始节点外，每个节点须有且仅有一个正常入口。",
                    node=node.id,
                    field=f"/definition/nodes/{index}",
                )
            if len(outgoing[node.id]) != (0 if node.type == "end" else 1):
                issue(
                    "output_count",
                    "除结束节点外，每个节点须有且仅有一个正常出口。",
                    node=node.id,
                    field=f"/definition/nodes/{index}",
                )

        remaining = {
            identifier: len(parents) for identifier, parents in incoming.items()
        }
        queue = deque(
            identifier for identifier, degree in remaining.items() if not degree
        )
        while queue:
            for successor in outgoing[queue.popleft()]:
                remaining[successor] -= 1
                if not remaining[successor]:
                    queue.append(successor)
        if any(remaining.values()):
            issue("cycle", "首版主流程不能包含自环或循环。", field="/definition/edges")
        starts = [node.id for node in nodes if node.type == "start"]
        if len(starts) == 1:
            reached, pending = set(), list(starts)
            while pending:
                identifier = pending.pop()
                if identifier in reached:
                    continue
                reached.add(identifier)
                pending.extend(outgoing[identifier])
            for index, node in enumerate(nodes):
                if node.id not in reached:
                    issue(
                        "node_unreachable",
                        "节点无法从开始节点到达。",
                        node=node.id,
                        field=f"/definition/nodes/{index}",
                    )

    presentation_ids = set()
    for index, item in enumerate(document.presentation.nodes):
        if item.node_id in presentation_ids:
            issue(
                "presentation_duplicate",
                "同一节点不能保存两份展示信息。",
                node=item.node_id,
                field=f"/presentation/nodes/{index}/node_id",
            )
        presentation_ids.add(item.node_id)
        if item.node_id not in by_id:
            issue(
                "presentation_node_missing",
                "展示信息引用了不存在的节点。",
                node=item.node_id,
                field=f"/presentation/nodes/{index}/node_id",
            )

    if context is not None:
        if context.compatibility != COMPATIBILITY:
            issue(
                "workflow_runtime_incompatible",
                "当前编译器、节点目录或状态版本不兼容。",
                field="/definition",
            )
        for index, node in enumerate(nodes):
            if node.type not in context.implemented_types:
                issue(
                    "node_implementation_unavailable",
                    "节点实现当前不可用，不能发布为可执行版本。",
                    node=node.id,
                    field=f"/definition/nodes/{index}/type",
                )
        selection = document.definition.defaults.selection or context.default_selection
        for role, identifier in selection.models.items():
            if identifier not in context.model_revision_ids:
                issue(
                    "model_revision_unavailable",
                    "模型配置修订当前不可用。",
                    field=f"/definition/defaults/selection/models/{role}",
                )
        for index, skill in enumerate(selection.skills.allowed):
            if skill not in context.skill_names:
                issue(
                    "skill_unavailable",
                    "所选 Skill 当前不可用。",
                    field=f"/definition/defaults/selection/skills/allowed/{index}",
                )
    return finish()


def verify_binding(
    binding: WorkflowBinding,
    revision: WorkflowRevision,
    *,
    thread_id: str,
    requested_ref: WorkflowRef | None = None,
    for_execution: bool = True,
) -> None:
    """Reject identity and compatibility changes; never choose a newer revision.

    for_execution=False permits an intact archive to be viewed when its code
    version is unavailable. A factory must still check installed handlers and
    the actual runtime before advertising or accepting execution.
    """
    reference = WorkflowRef(
        workflow_id=revision.workflow_id, revision_id=revision.revision_id
    )
    if binding.thread_id != thread_id or binding.workflow_ref != reference:
        raise WorkflowContractError("workflow_binding_mismatch")
    if requested_ref is not None and requested_ref != reference:
        raise WorkflowContractError("workflow_binding_conflict")
    if revision.semantic_hash != semantic_hash(revision.document.definition):
        raise WorkflowContractError("workflow_revision_hash_mismatch")
    if (
        binding.semantic_hash != revision.semantic_hash
        or binding.compatibility != revision.compatibility
    ):
        raise WorkflowContractError("workflow_binding_mismatch")
    if for_execution and revision.compatibility != COMPATIBILITY:
        raise WorkflowContractError("workflow_runtime_incompatible")


def normal_successor(
    document: WorkflowDocument,
    node_id: str,
    result: WorkflowBusinessResult,
) -> str | None:
    """Choose exactly one normal successor, or a system terminal outcome.

    Call only after validating the complete definition. LangGraph END mapping
    and state updates belong to the compiler; no second routing edge is added.
    """
    node = next(
        (node for node in document.definition.nodes if node.id == node_id), None
    )
    description = node_types().get(node.type) if node else None
    if description is None or result.outcome not in description.outcomes:
        raise WorkflowContractError("workflow_business_outcome_invalid")
    if result.outcome != "continue" or node.type == "end":
        return None
    edges = [edge for edge in document.definition.edges if edge.source == node_id]
    if len(edges) != 1:
        raise WorkflowContractError("workflow_successor_invalid")
    return edges[0].target
