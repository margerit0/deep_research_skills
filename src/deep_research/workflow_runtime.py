"""Resolve immutable workflow bindings for publication, execution and observation."""

from __future__ import annotations

import os

from langgraph_sdk.runtime import ServerRuntime
from starlette.exceptions import HTTPException

from deep_research.atlas_runtime import submissions_enabled
from deep_research.run_configuration import (
    catalog,
    resolve_selection,
    validate_snapshot,
)
from deep_research.submission_journal import get_submission_journal
from deep_research.workflow_compiler import compile_workflow
from deep_research.workflow_definition import WorkflowRef, WorkflowSelection
from deep_research.workflow_nodes import implementations
from deep_research.workflow_registry import COMPATIBILITY, standard_document
from deep_research.workflow_store import WorkflowStore, WorkflowStoreError
from deep_research.workflow_validation import (
    PublicationContext,
    WorkflowContractError,
    validate_document,
)

GRAPH_ID = "research_workflow"


def _require_runtime():
    if (
        not submissions_enabled()
        or os.getenv("ATLAS_WORKFLOW_EXECUTION_ENABLED", "true").lower() == "false"
    ):
        raise WorkflowContractError("workflow_runtime_unavailable")


def require_executable(revision):
    """Check archived structure, code and runtime before any native run is created."""
    _require_runtime()
    if revision.compatibility != COMPATIBILITY:
        raise WorkflowContractError("workflow_runtime_incompatible")
    if not validate_document(revision.document).valid:
        raise WorkflowContractError("workflow_definition_invalid")
    installed = implementations()
    for node in revision.document.definition.nodes:
        if node.type not in {"start", "end"} and not callable(
            installed.get((node.type, node.type_version))
        ):
            raise WorkflowContractError("node_implementation_unavailable")


def publication_context(document):
    """Build publication evidence from installed code and server-owned directories."""
    try:
        _require_runtime()
        directory = catalog()
        defaults = WorkflowSelection.model_validate(
            {
                "version": 1,
                "models": directory["defaults"],
                "skills": {"mode": "auto", "allowed": []},
            }
        )
        installed = implementations()
        context = PublicationContext(
            compatibility=COMPATIBILITY,
            implemented_types=frozenset(
                {
                    "start",
                    "end",
                    *(
                        name
                        for (name, version), handler in installed.items()
                        if version == 1 and callable(handler)
                    ),
                }
            ),
            model_revision_ids=frozenset(item["id"] for item in directory["models"]),
            skill_names=frozenset(item["name"] for item in directory["skills"]),
            default_selection=defaults,
        )
        if validate_document(document, checked_edit_version=1, context=context).valid:
            selection = document.definition.defaults.selection or defaults
            # Resolve and verify real archived definitions, without invoking a model.
            validate_snapshot(resolve_selection(selection.model_dump(mode="json")))
            compile_workflow(document, handlers=installed)
        return context
    except WorkflowStoreError:
        raise
    except Exception as exc:
        raise WorkflowStoreError("workflow_runtime_unavailable", 503) from exc


def check_ready():
    """Verify actual implementations and publication dependencies for capability discovery."""
    document = standard_document()
    context = publication_context(document)
    if not validate_document(document, checked_edit_version=1, context=context).valid:
        raise WorkflowContractError("workflow_runtime_unavailable")
    if not {"optimize_plan", "organize_notes"} <= context.implemented_types:
        raise WorkflowContractError("node_implementation_unavailable")


def validate_record(record, *, for_execution=False):
    """Resolve acceptance evidence independently of any client configuration."""
    store = WorkflowStore(get_submission_journal())
    with store.connection() as db:
        resolved = store.verify_record(db, record, for_execution=for_execution)
    if resolved is not None and for_execution:
        require_executable(resolved[1])
    return resolved


def graph(config, runtime: ServerRuntime):
    """Use the same bound topology for runs and native state/history requests."""
    try:
        configurable = config.get("configurable", {})
        thread_id = configurable.get("thread_id")
        if not thread_id and runtime.access_context == "assistants.read":
            return compile_workflow(standard_document(), observe=True)
        journal = get_submission_journal()
        if journal is None:
            raise WorkflowContractError("workflow_runtime_unavailable")
        store = WorkflowStore(journal)
        executing = runtime.access_context == "threads.create_run"
        reference = configurable.get("workflow_ref")
        binding, revision = store.resolve(
            str(thread_id or ""),
            for_execution=executing,
            requested_ref=WorkflowRef.model_validate(reference) if reference else None,
        )
        if not executing:
            # Intact v1 archives stay observable when an implementation is absent.
            if revision.compatibility.state_schema_version != 1:
                raise WorkflowContractError("workflow_state_schema_unavailable")
            return compile_workflow(revision.document, binding=binding, observe=True)
        require_executable(revision)

        def verify_entry(state, run_config, node):
            metadata = run_config.get("metadata", {})
            runtime_ids = run_config.get("configurable", {})
            if (
                metadata.get("atlas_submission_version") != 1
                or str(runtime_ids.get("thread_id")) != binding.thread_id
            ):
                raise WorkflowContractError("workflow_acceptance_required")
            record = journal.get(binding.thread_id, metadata.get("atlas_turn_id"))
            if record is None or record["research_id"] != metadata.get(
                "atlas_research_id"
            ):
                raise WorkflowContractError("workflow_acceptance_required")
            accepted = validate_record(record, for_execution=True)
            attempt = record["attempts"][-1]
            if (
                accepted is None
                or accepted[0] != binding
                or attempt["run_id"] != str(runtime_ids.get("run_id"))
                or attempt["attempt_id"] != metadata.get("atlas_attempt_id")
                or metadata.get("atlas_workflow_ref")
                != binding.workflow_ref.model_dump()
                or metadata.get("atlas_workflow_hash") != binding.semantic_hash
            ):
                raise WorkflowContractError("workflow_binding_mismatch")
            expected_fields = (
                ("research_id", "turn_id")
                if node.type == "prepare_research"
                else ("active_research_id", "active_turn_id")
            )
            if (state.get(expected_fields[0]), state.get(expected_fields[1])) != (
                record["research_id"],
                record["turn_id"],
            ):
                raise WorkflowContractError("workflow_execution_identity_mismatch")

        return compile_workflow(
            revision.document, binding=binding, verify_entry=verify_entry
        )
    except WorkflowContractError as exc:
        raise HTTPException(409, exc.reason) from exc
    except WorkflowStoreError as exc:
        raise HTTPException(exc.status, exc.reason) from exc
