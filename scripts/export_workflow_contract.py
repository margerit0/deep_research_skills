"""Export/check the M1 wire schema and shared examples without model imports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic.json_schema import models_json_schema

from deep_research import workflow_definition as wire
from deep_research.workflow_registry import (
    COMPATIBILITY,
    WorkflowNodeCatalog,
    node_catalog,
    standard_document,
)
from deep_research.workflow_validation import validate_document

ROOT = Path(__file__).resolve().parents[1]
MODELS = (
    wire.WorkflowDocument,
    wire.WorkflowDraft,
    wire.WorkflowRevision,
    wire.WorkflowRef,
    wire.WorkflowBinding,
    wire.WorkflowValidation,
    wire.CreateWorkflowRequest,
    wire.SaveDraftRequest,
    wire.ValidateWorkflowRequest,
    wire.PublishWorkflowRequest,
    wire.ArchiveWorkflowRequest,
    wire.WorkflowSummary,
    wire.WorkflowRevisionSummary,
    wire.WorkflowPage,
    wire.WorkflowRevisionPage,
    wire.WorkflowConflict,
    wire.WorkflowNodeEvent,
    wire.WorkflowBusinessResult,
    WorkflowNodeCatalog,
)


def artifacts() -> dict[Path, str]:
    """Build deterministic files checked by both Python and TypeScript tests."""
    document = standard_document()
    at = "2026-11-15T00:00:00Z"
    reference = wire.WorkflowRef(
        workflow_id="workflow-example", revision_id="revision-example"
    )
    revision = wire.WorkflowRevision(
        **reference.model_dump(),
        revision_number=1,
        source_edit_version=7,
        semantic_hash=wire.semantic_hash(document.definition),
        compatibility=COMPATIBILITY,
        document=document,
        published_at=at,
    )
    revision_summary = wire.WorkflowRevisionSummary.model_validate(
        revision.model_dump(include=set(wire.WorkflowRevisionSummary.model_fields))
    )
    summary = wire.WorkflowSummary(
        workflow_id=reference.workflow_id,
        name=document.name,
        archived=False,
        edit_version=8,
        base_revision_id=reference.revision_id,
        latest_revision=revision_summary,
        created_at=at,
        updated_at=at,
    )
    examples = {
        "WorkflowDocument": document,
        "WorkflowDraft": wire.WorkflowDraft(
            workflow_id=reference.workflow_id,
            edit_version=7,
            document=document,
            updated_at=at,
        ),
        "WorkflowRevision": revision,
        "WorkflowRef": reference,
        "WorkflowBinding": wire.WorkflowBinding(
            thread_id="thread-example",
            workflow_ref=reference,
            semantic_hash=revision.semantic_hash,
            compatibility=COMPATIBILITY,
            bound_at=at,
        ),
        "WorkflowValidation": validate_document(document, checked_edit_version=7),
        "CreateWorkflowRequest": wire.CreateWorkflowRequest(
            request_id="create-example",
            name="新流程",
            source=wire.TemplateSource(
                kind="template", template_id="standard_research"
            ),
        ),
        "SaveDraftRequest": wire.SaveDraftRequest(
            expected_edit_version=7, document=document
        ),
        "ValidateWorkflowRequest": wire.ValidateWorkflowRequest(
            expected_edit_version=7
        ),
        "PublishWorkflowRequest": wire.PublishWorkflowRequest(
            expected_edit_version=7, request_id="publish-example"
        ),
        "ArchiveWorkflowRequest": wire.ArchiveWorkflowRequest(expected_edit_version=8),
        "WorkflowSummary": summary,
        "WorkflowRevisionSummary": revision_summary,
        "WorkflowPage": wire.WorkflowPage(items=[summary], next_cursor=None),
        "WorkflowRevisionPage": wire.WorkflowRevisionPage(
            items=[revision_summary], next_cursor=None
        ),
        "WorkflowConflict": wire.WorkflowConflict(
            reason="workflow_edit_conflict", current_edit_version=8
        ),
        "WorkflowNodeEvent": wire.WorkflowNodeEvent(
            id="00000000-0000-4000-8000-000000000001",
            thread_id="thread-example",
            research_id="research-example",
            turn_id="turn-example",
            attempt_id="turn-example",
            run_id="00000000-0000-4000-8000-000000000002",
            workflow_ref=reference,
            semantic_hash=revision.semantic_hash,
            node_id="write_research_brief",
            node_type="write_research_brief",
            sequence=1,
            at=at,
            kind="started",
            elapsed_ms=0,
        ),
        "WorkflowBusinessResult": wire.WorkflowBusinessResult(outcome="continue"),
        "WorkflowNodeCatalog": node_catalog(),
    }
    _, schema = models_json_schema(
        [(model, "validation") for model in MODELS], title="Atlas workflow contract v1"
    )
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:atlas:workflow:v1",
        **schema,
    }
    configured = document.model_copy(deep=True)
    configured.definition.defaults.selection = wire.WorkflowSelection(
        models=dict.fromkeys(wire.MODEL_ROLES, "a" * 64),
        skills=wire.WorkflowSkills(mode="manual", allowed=["beta", "alpha"]),
    )
    processing = configured.model_copy(deep=True)
    processing.definition.nodes.append(
        wire.NodeDefinition(
            id="plan_a",
            type="optimize_plan",
            parameters={
                "instructions": "比较市场。\n保留来源 😀 \u2028 对照不同观点。"
            },
        )
    )
    processing.definition.edges[3].target = "plan_a"
    processing.definition.edges.append(
        wire.EdgeDefinition(
            id="edge_plan",
            source="plan_a",
            target="supervisor_subgraph",
        )
    )
    hash_examples = {
        name: {
            "definition": item.definition.model_dump(mode="json"),
            "semantic_hash": wire.semantic_hash(item.definition),
        }
        for name, item in (
            ("standard", document),
            ("configured", configured),
            ("processing", processing),
        )
    }
    values = {
        ROOT / "docs/contracts/workflow-v1.schema.json": schema,
        ROOT / "tests/fixtures/workflows/v1-wire-examples.json": {
            "schema_version": 1,
            "examples": {
                name: model.model_dump(mode="json") for name, model in examples.items()
            },
            "hash_examples": hash_examples,
        },
    }
    return {
        path: json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        for path, value in values.items()
    }


def main() -> int:
    """Write generated artifacts, or fail a check without changing files."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for path, content in artifacts().items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                parser.exit(
                    1,
                    f"Workflow contract artifact is stale: {path.relative_to(ROOT)}\n",
                )
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
