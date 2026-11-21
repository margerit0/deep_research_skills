"""Define the versioned workflow wire contract without importing graphs or models.

These types describe drafts and append-only publication records. The store,
not Python object freezing, must enforce revision immutability and transactions.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

MAX_NODES = 30
MAX_EDGES = 60
MAX_DOCUMENT_BYTES = 262_144
MAX_SAFE_INTEGER = 9_007_199_254_740_991
MODEL_ROLES = (
    "SCOPING",
    "SUPERVISOR",
    "RESEARCHER",
    "SUMMARIZATION",
    "COMPRESSION",
    "FINAL_REPORT",
)
ModelRole = Literal[
    "SCOPING",
    "SUPERVISOR",
    "RESEARCHER",
    "SUMMARIZATION",
    "COMPRESSION",
    "FINAL_REPORT",
]
VersionOne = Annotated[int, Field(strict=True, ge=1, le=1)]
PositiveVersion = Annotated[int, Field(strict=True, ge=1, le=MAX_SAFE_INTEGER)]
Identifier = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
]
NodeId = Annotated[
    str, Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
UuidText = Annotated[
    str,
    Field(pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$"),
]
Name = Annotated[str, Field(min_length=1, max_length=120, pattern=r"\S")]


def _timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("A timestamp must include its UTC offset")
    return value


Timestamp = Annotated[
    str,
    Field(
        pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$",
        json_schema_extra={"format": "date-time"},
    ),
    AfterValidator(_timestamp),
]


class WireModel(BaseModel):
    """Reject implicit scalar conversion, non-finite numbers and unknown fields."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class WorkflowSkills(WireModel):
    """Describe allowed Skills using the existing selection semantics."""

    mode: Literal["auto", "manual"]
    allowed: list[Name] = Field(max_length=100)

    @model_validator(mode="after")
    def valid_allowed(self) -> WorkflowSkills:
        """Reject duplicates and a misleading allowlist in automatic mode."""
        if len(self.allowed) != len(set(self.allowed)):
            raise ValueError("Duplicate Skills are not allowed")
        if self.mode == "auto" and self.allowed:
            raise ValueError("Automatic Skills must have an empty allowlist")
        return self


class WorkflowSelection(WireModel):
    """Keep six role revisions; instances cannot override their role's model."""

    version: VersionOne = 1
    models: dict[ModelRole, Digest]
    skills: WorkflowSkills

    @model_validator(mode="after")
    def complete_roles(self) -> WorkflowSelection:
        """Require the same complete role set as run_configuration.Selection."""
        if set(self.models) != set(MODEL_ROLES):
            raise ValueError("All six model roles are required")
        return self


class WorkflowDefaults(WireModel):
    """Supply optional defaults; acceptance still fixes the effective snapshot."""

    selection: WorkflowSelection | None = None


class NodeDefinition(WireModel):
    """Identify a node independently of its editable display label."""

    id: NodeId
    type: NodeId
    type_version: PositiveVersion = 1
    parameters: dict[
        Literal["instructions"], Annotated[str, Field(max_length=4000)]
    ] = Field(default_factory=dict, max_length=1)


class EdgeDefinition(WireModel):
    """Connect normal control-flow ports, without arbitrary expressions."""

    id: Identifier
    source: NodeId
    source_port: Literal["out"] = "out"
    target: NodeId
    target_port: Literal["in"] = "in"


class WorkflowDefinition(WireModel):
    """Keep executable fields separate from layout and transient run state."""

    schema_version: VersionOne = 1
    nodes: list[NodeDefinition] = Field(max_length=MAX_NODES)
    edges: list[EdgeDefinition] = Field(max_length=MAX_EDGES)
    defaults: WorkflowDefaults = Field(default_factory=WorkflowDefaults)


class Position(WireModel):
    """Store finite canvas coordinates within a bounded editing area."""

    x: float = Field(ge=-1_000_000, le=1_000_000)
    y: float = Field(ge=-1_000_000, le=1_000_000)


class NodePresentation(WireModel):
    """Save one optional label and position for a node."""

    node_id: NodeId
    label: Name
    position: Position


class Viewport(Position):
    """Save the viewport independently of executable node parameters."""

    zoom: float = Field(ge=0.2, le=2.0)


class WorkflowPresentation(WireModel):
    """Allow omitted positions so a new draft can receive automatic layout."""

    schema_version: VersionOne = 1
    nodes: list[NodePresentation] = Field(default_factory=list, max_length=MAX_NODES)
    viewport: Viewport = Field(default_factory=lambda: Viewport(x=0, y=0, zoom=1))


class WorkflowDocument(WireModel):
    """Represent the content saved atomically with an optimistic edit version."""

    name: Name
    definition: WorkflowDefinition
    presentation: WorkflowPresentation = Field(default_factory=WorkflowPresentation)


class WorkflowRef(WireModel):
    """Reference a server-owned publication, never a browser execution graph."""

    workflow_id: Identifier
    revision_id: Identifier


class WorkflowCompatibility(WireModel):
    """Pin implementations independently of the API's schema version."""

    graph_id: Literal["research_workflow"] = "research_workflow"
    compiler_version: PositiveVersion
    node_registry_version: PositiveVersion
    state_schema_version: PositiveVersion


class WorkflowDraft(WireModel):
    """Describe the current replaceable draft and its concurrency token."""

    schema_version: VersionOne = 1
    workflow_id: Identifier
    edit_version: PositiveVersion
    base_revision_id: Identifier | None = None
    document: WorkflowDocument
    updated_at: Timestamp


def semantic_hash(definition: WorkflowDefinition) -> str:
    """Hash behavior, excluding labels, positions, array order and edge IDs."""
    value = definition.model_dump(mode="json")
    value["nodes"] = sorted(value["nodes"], key=lambda node: node["id"])
    value["edges"] = sorted(
        (
            {key: item for key, item in edge.items() if key != "id"}
            for edge in value["edges"]
        ),
        key=lambda edge: (
            edge["source"],
            edge["source_port"],
            edge["target"],
            edge["target_port"],
        ),
    )
    selection = value["defaults"]["selection"]
    if selection is not None:
        selection["skills"]["allowed"].sort()
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class WorkflowRevision(WireModel):
    """Describe one append-only revision; validate archive integrity on read."""

    schema_version: VersionOne = 1
    workflow_id: Identifier
    revision_id: Identifier
    revision_number: PositiveVersion
    source_edit_version: PositiveVersion
    semantic_hash: Digest
    compatibility: WorkflowCompatibility
    document: WorkflowDocument
    note: str = Field(default="", max_length=2000)
    published_at: Timestamp

    @model_validator(mode="after")
    def hash_matches(self) -> WorkflowRevision:
        """Reject corrupted behavior without silently repairing its digest."""
        if self.semantic_hash != semantic_hash(self.document.definition):
            raise ValueError("workflow_revision_hash_mismatch")
        return self


class WorkflowBinding(WireModel):
    """Pin a native thread to a revision in the submission transaction."""

    schema_version: VersionOne = 1
    thread_id: Identifier
    workflow_ref: WorkflowRef
    semantic_hash: Digest
    compatibility: WorkflowCompatibility
    bound_at: Timestamp


class ValidationIssue(WireModel):
    """Expose safe messages and stable locations, without provider payloads."""

    code: Identifier
    severity: Literal["error", "warning"] = "error"
    message: str = Field(min_length=1, max_length=500)
    node_id: NodeId | None = None
    edge_id: Identifier | None = None
    field: str | None = Field(default=None, max_length=500)


class WorkflowValidation(WireModel):
    """Associate validation with the exact saved version when supplied."""

    schema_version: VersionOne = 1
    scope: Literal["structure", "publication"] = "structure"
    valid: bool
    checked_edit_version: PositiveVersion | None = None
    issues: list[ValidationIssue] = Field(max_length=100)
    truncated: bool = False

    @model_validator(mode="after")
    def consistent_result(self) -> WorkflowValidation:
        """Prevent a success label alongside errors or an incomplete result."""
        if self.scope == "publication" and self.checked_edit_version is None:
            raise ValueError("workflow_validation_version_missing")
        if self.valid != (
            not self.truncated and not any(i.severity == "error" for i in self.issues)
        ):
            raise ValueError("workflow_validation_result_inconsistent")
        return self


class TemplateSource(WireModel):
    """Create from the built-in standard research template."""

    kind: Literal["template"]
    template_id: Literal["standard_research"]


class RevisionSource(WireModel):
    """Copy a published revision without inheriting its identity."""

    kind: Literal["revision"]
    workflow_ref: WorkflowRef


class ImportSource(WireModel):
    """Import document content only, excluding revisions and run records."""

    kind: Literal["import"]
    document: WorkflowDocument


class CreateWorkflowRequest(WireModel):
    """Give creation an idempotency key before any HTTP request is sent."""

    request_id: Identifier
    name: Name
    source: Annotated[
        TemplateSource | RevisionSource | ImportSource, Field(discriminator="kind")
    ]


class SaveDraftRequest(WireModel):
    """Reject stale edits rather than silently replacing a newer draft."""

    expected_edit_version: PositiveVersion
    document: WorkflowDocument


class ValidateWorkflowRequest(WireModel):
    """Validate only an exact stored edit version."""

    expected_edit_version: PositiveVersion


class PublishWorkflowRequest(ValidateWorkflowRequest):
    """Reuse the same key and content when a publication response is lost."""

    request_id: Identifier
    note: str = Field(default="", max_length=2000)


class ArchiveWorkflowRequest(ValidateWorkflowRequest):
    """Archive only the draft version the user reviewed."""


class WorkflowRevisionSummary(WireModel):
    """Project a publication without loading its document into a list view."""

    workflow_id: Identifier
    revision_id: Identifier
    revision_number: PositiveVersion
    source_edit_version: PositiveVersion
    semantic_hash: Digest
    note: str = Field(max_length=2000)
    published_at: Timestamp


class WorkflowSummary(WireModel):
    """Describe a workflow and its current draft, including archived records."""

    workflow_id: Identifier
    name: Name
    archived: bool
    edit_version: PositiveVersion
    base_revision_id: Identifier | None
    latest_revision: WorkflowRevisionSummary | None
    created_at: Timestamp
    updated_at: Timestamp


class WorkflowPage(WireModel):
    """Page newest-created workflows with an exclusive creation-order cursor."""

    schema_version: VersionOne = 1
    items: list[WorkflowSummary] = Field(max_length=100)
    next_cursor: PositiveVersion | None


class WorkflowRevisionPage(WireModel):
    """Page immutable revisions in descending revision-number order."""

    schema_version: VersionOne = 1
    items: list[WorkflowRevisionSummary] = Field(max_length=100)
    next_cursor: PositiveVersion | None


class WorkflowConflict(WireModel):
    """Return enough information to preserve a local draft and reload safely."""

    reason: Literal[
        "workflow_edit_conflict",
        "workflow_request_conflict",
        "workflow_archived",
        "workflow_binding_conflict",
        "legacy_workflow_locked",
    ]
    current_edit_version: PositiveVersion | None = None


class WorkflowNodeEvent(WireModel):
    """Describe parent-node observations separately from dynamic researchers."""

    version: VersionOne = 1
    id: UuidText
    thread_id: Identifier
    research_id: Identifier
    turn_id: Identifier
    run_id: UuidText
    attempt_id: Identifier
    workflow_ref: WorkflowRef
    semantic_hash: Digest
    node_id: NodeId
    node_type: NodeId
    sequence: PositiveVersion
    at: Timestamp
    kind: Literal["started", "completed", "awaiting_input", "failed", "partial"]
    elapsed_ms: int = Field(ge=0, le=MAX_SAFE_INTEGER)
    summary: str = Field(default="", max_length=2000)


class WorkflowBusinessResult(WireModel):
    """Return a routing outcome without exposing an arbitrary goto target.

    Runtime updates remain in the graph adapter because they can include
    LangChain messages and Overwrite objects, which are not public JSON.
    """

    outcome: Literal["continue", "awaiting_input", "failed", "partial"]
