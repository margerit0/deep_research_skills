"""M1 protocol, topology and ownership checks; never load model implementations."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from deep_research import workflow_definition as wire
from deep_research.workflow_registry import (
    COMPATIBILITY,
    SAFE_NODE_TYPES,
    node_types,
    standard_document,
)
from deep_research.workflow_validation import (
    PublicationContext,
    WorkflowContractError,
    normal_successor,
    validate_document,
    verify_binding,
)
from scripts.export_workflow_contract import MODELS, artifacts

FIXTURES = Path(__file__).parent / "fixtures/workflows"
EXAMPLES = json.loads((FIXTURES / "v1-wire-examples.json").read_text(encoding="utf-8"))[
    "examples"
]
CASES = json.loads((FIXTURES / "v1-cases.json").read_text(encoding="utf-8"))["cases"]


def case_documents():
    documents = {}
    for case in CASES:
        value = copy.deepcopy(
            documents[case["base"]] if case["base"] else EXAMPLES["WorkflowDocument"]
        )
        for change in case["changes"]:
            parts = change["path"].strip("/").split("/")
            current = value
            for part in parts[:-1]:
                current = (
                    current[int(part)] if isinstance(current, list) else current[part]
                )
            key = int(parts[-1]) if isinstance(current, list) else parts[-1]
            if change["op"] == "set":
                current[key] = copy.deepcopy(change["value"])
            elif change["op"] == "remove":
                if isinstance(current, list):
                    current.pop(key)
                else:
                    del current[key]
            else:
                current[key].append(copy.deepcopy(change["value"]))
        documents[case["id"]] = value
    return documents


DOCUMENTS = case_documents()


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_shared_structural_cases(case):
    document = DOCUMENTS[case["id"]]
    if case["schema_valid"]:
        wire.WorkflowDocument.model_validate(document)
    else:
        with pytest.raises(ValidationError):
            wire.WorkflowDocument.model_validate(document)
    result = validate_document(document, checked_edit_version=7)
    assert sorted({issue.code for issue in result.issues}) == case["codes"]
    assert result.valid == (not case["codes"])
    assert result.scope == "structure"
    assert result.checked_edit_version == 7
    assert "synthetic-sensitive-value" not in result.model_dump_json()
    assert all(issue.field and issue.field.startswith("/") for issue in result.issues)


@pytest.mark.parametrize("model", MODELS, ids=lambda model: model.__name__)
def test_shared_wire_examples(model):
    value = EXAMPLES[model.__name__]
    assert model.model_validate(value).model_dump(mode="json") == value


def test_generated_schema_and_examples_are_current():
    for path, expected in artifacts().items():
        assert path.read_text(encoding="utf-8") == expected, path


def test_contract_import_does_not_construct_models_or_read_graphs():
    subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import deep_research.workflow_validation; "
                "assert not {'deep_research.model_config', 'deep_research.research_agent_full', "
                "'langchain_openai', 'deep_research.skills_loader'} & set(sys.modules)"
            ),
        ],
        check=True,
        timeout=15,
    )


def test_directory_preserves_core_names_roles_recovery_and_evidence():
    from deep_research.run_configuration import ROLES
    from deep_research.submission_journal import SAFE_NODES
    from tests.atlas_workflow_factory import CORE

    directory = node_types()
    assert set(directory) == {*CORE, "start", "end", "optimize_plan", "organize_notes"}
    assert set(wire.MODEL_ROLES) == set(ROLES)
    assert SAFE_NODE_TYPES == set(SAFE_NODES)
    for name in (*CORE, "start", "end"):
        assert directory[name].fixed_id == name
        assert directory[name].max_instances == 1
    assert directory["clarify_with_user"].min_instances == 0
    assert directory["optimize_plan"].state_writes == {
        "research_brief": "replace",
        "supervisor_messages": "overwrite",
    }
    assert directory["organize_notes"].state_writes == {"organized_notes": "replace"}
    assert not directory["organize_notes"].safe_recovery
    directory["organize_notes"].state_writes["sources"] = "replace"
    assert "sources" not in node_types()["organize_notes"].state_writes


def document_with_plans(count):
    value = copy.deepcopy(EXAMPLES["WorkflowDocument"])
    nodes = value["definition"]["nodes"]
    nodes[4:4] = [
        {
            "id": f"plan_{index}",
            "type": "optimize_plan",
            "parameters": {"instructions": "核对证据"},
        }
        for index in range(count)
    ]
    value["definition"]["edges"] = [
        {"id": f"edge_{index}", "source": before["id"], "target": after["id"]}
        for index, (before, after) in enumerate(zip(nodes, nodes[1:]))
    ]
    return value


@pytest.mark.parametrize("extra,valid", [(23, True), (24, False)])
def test_node_limit_is_for_main_nodes_including_system_nodes(extra, valid):
    assert validate_document(document_with_plans(extra)).valid is valid


@pytest.mark.parametrize("count,valid", [(4000, True), (4001, False)])
def test_instructions_use_unicode_code_point_limits(count, valid):
    value = copy.deepcopy(DOCUMENTS["extensions"])
    value["definition"]["nodes"][7]["parameters"]["instructions"] = "😀" * count
    assert validate_document(value).valid is valid


def test_total_size_is_utf8_and_diagnostics_do_not_echo_input():
    value = copy.deepcopy(DOCUMENTS["extensions"])
    value["definition"]["nodes"][7]["parameters"]["instructions"] = "密" * 90_000
    result = validate_document(value)
    assert [issue.code for issue in result.issues] == ["document_too_large"]
    assert len(result.model_dump_json()) < 500


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_coordinates_are_rejected(value):
    document = copy.deepcopy(EXAMPLES["WorkflowDocument"])
    document["presentation"]["viewport"]["x"] = value
    assert [issue.code for issue in validate_document(document).issues] == [
        "schema_invalid"
    ]


def test_semantic_hash_ignores_layout_names_and_serialization_order():
    document = standard_document()
    expected = "83fbeb3d4447f8f46d9b50f8c865887305e362f1125b46783eee60110404ed20"
    assert wire.semantic_hash(document.definition) == expected
    document.name = "重命名流程"
    document.presentation.nodes = [
        wire.NodePresentation(
            node_id="start",
            label="新入口名称",
            position=wire.Position(x=800, y=-25),
        )
    ]
    document.definition.nodes.reverse()
    document.definition.edges.reverse()
    for index, edge in enumerate(document.definition.edges):
        edge.id = f"renamed_edge_{index}"
    assert wire.semantic_hash(document.definition) == expected


def selection():
    return wire.WorkflowSelection(
        models=dict.fromkeys(wire.MODEL_ROLES, "a" * 64),
        skills=wire.WorkflowSkills(mode="manual", allowed=["beta", "alpha"]),
    )


def test_semantic_hash_changes_for_behavior_but_not_skill_order():
    document = wire.WorkflowDocument.model_validate(DOCUMENTS["extensions"])
    before = wire.semantic_hash(document.definition)
    document.definition.nodes[7].parameters["instructions"] = "新的要求"
    assert wire.semantic_hash(document.definition) != before
    before = wire.semantic_hash(document.definition)
    document.definition.defaults.selection = selection()
    assert wire.semantic_hash(document.definition) != before
    before = wire.semantic_hash(document.definition)
    document.definition.defaults.selection.skills.allowed.reverse()
    assert wire.semantic_hash(document.definition) == before


def publication_context(**changes):
    return PublicationContext(
        **{
            "compatibility": COMPATIBILITY,
            "implemented_types": frozenset(node_types()),
            "model_revision_ids": frozenset({"a" * 64}),
            "skill_names": frozenset({"alpha", "beta"}),
            "default_selection": selection(),
            **changes,
        }
    )


def test_publication_requires_implementations_and_configuration_availability():
    value = copy.deepcopy(DOCUMENTS["extensions"])
    assert validate_document(value).scope == "structure"
    with pytest.raises(WorkflowContractError, match="workflow_edit_version_required"):
        validate_document(value, context=publication_context())
    good = validate_document(
        value, checked_edit_version=7, context=publication_context()
    )
    assert good.scope == "publication" and good.valid
    missing = validate_document(
        value,
        checked_edit_version=7,
        context=publication_context(
            implemented_types=frozenset(node_types()) - {"optimize_plan"},
        ),
    )
    assert {issue.code for issue in missing.issues} == {
        "node_implementation_unavailable"
    }
    chosen = selection().model_dump()
    chosen["models"]["SCOPING"] = "b" * 64
    chosen["skills"]["allowed"] = ["missing"]
    value["definition"]["defaults"]["selection"] = chosen
    bad = validate_document(
        value, checked_edit_version=7, context=publication_context()
    )
    assert {issue.code for issue in bad.issues} == {
        "model_revision_unavailable",
        "skill_unavailable",
    }


def test_default_configuration_is_checked_even_when_the_workflow_inherits_it():
    result = validate_document(
        standard_document(),
        checked_edit_version=7,
        context=publication_context(model_revision_ids=frozenset()),
    )
    assert not result.valid and {issue.code for issue in result.issues} == {
        "model_revision_unavailable"
    }


def test_publication_refuses_unavailable_compiler_versions():
    result = validate_document(
        standard_document(),
        checked_edit_version=7,
        context=publication_context(
            compatibility=COMPATIBILITY.model_copy(update={"compiler_version": 2}),
        ),
    )
    assert {issue.code for issue in result.issues} == {"workflow_runtime_incompatible"}


@pytest.mark.parametrize(
    "fault", ["missing_role", "unknown_role", "auto_allowlist", "duplicate_skills"]
)
def test_selection_preserves_the_existing_six_role_contract(fault):
    value = selection().model_dump()
    if fault == "missing_role":
        del value["models"]["SCOPING"]
    elif fault == "unknown_role":
        value["models"]["CUSTOM"] = "a" * 64
    elif fault == "auto_allowlist":
        value["skills"]["mode"] = "auto"
    else:
        value["skills"]["allowed"] = ["alpha", "alpha"]
    with pytest.raises(ValidationError):
        wire.WorkflowSelection.model_validate(value)


def test_revision_read_rejects_changed_behavior_instead_of_rehashing_it():
    value = copy.deepcopy(EXAMPLES["WorkflowRevision"])
    value["document"]["definition"]["nodes"][0]["type_version"] = 2
    with pytest.raises(ValidationError, match="workflow_revision_hash_mismatch"):
        wire.WorkflowRevision.model_validate(value)


def test_binding_uses_original_revision_for_omitted_ref_and_rejects_switches():
    revision = wire.WorkflowRevision.model_validate(EXAMPLES["WorkflowRevision"])
    binding = wire.WorkflowBinding.model_validate(EXAMPLES["WorkflowBinding"])
    verify_binding(binding, revision, thread_id=binding.thread_id)
    with pytest.raises(WorkflowContractError, match="workflow_binding_conflict"):
        verify_binding(
            binding,
            revision,
            thread_id=binding.thread_id,
            requested_ref=wire.WorkflowRef(
                workflow_id=revision.workflow_id, revision_id="new-revision"
            ),
        )
    with pytest.raises(WorkflowContractError, match="workflow_binding_mismatch"):
        verify_binding(binding, revision, thread_id="another-thread")
    binding.semantic_hash = "0" * 64
    with pytest.raises(WorkflowContractError, match="workflow_binding_mismatch"):
        verify_binding(binding, revision, thread_id=binding.thread_id)


def test_intact_history_can_be_viewed_when_its_compiler_is_unavailable():
    revision = wire.WorkflowRevision.model_validate(EXAMPLES["WorkflowRevision"])
    binding = wire.WorkflowBinding.model_validate(EXAMPLES["WorkflowBinding"])
    revision.compatibility.compiler_version = binding.compatibility.compiler_version = 2
    verify_binding(binding, revision, thread_id=binding.thread_id, for_execution=False)
    with pytest.raises(WorkflowContractError, match="workflow_runtime_incompatible"):
        verify_binding(binding, revision, thread_id=binding.thread_id)


def test_system_outcomes_never_follow_the_normal_successor():
    document = wire.WorkflowDocument.model_validate(DOCUMENTS["extensions"])
    assert (
        normal_successor(
            document, "plan_a", wire.WorkflowBusinessResult(outcome="continue")
        )
        == "supervisor_subgraph"
    )
    assert (
        normal_successor(
            document,
            "clarify_with_user",
            wire.WorkflowBusinessResult(outcome="awaiting_input"),
        )
        is None
    )
    assert (
        normal_successor(
            document, "plan_a", wire.WorkflowBusinessResult(outcome="failed")
        )
        is None
    )
    with pytest.raises(
        WorkflowContractError, match="workflow_business_outcome_invalid"
    ):
        normal_successor(
            document, "plan_a", wire.WorkflowBusinessResult(outcome="awaiting_input")
        )
    with pytest.raises(ValidationError):
        wire.WorkflowBusinessResult.model_validate(
            {"outcome": "continue", "goto": "arbitrary"}
        )


@pytest.mark.parametrize("version", [0, -1, True, "7", 1.5, wire.MAX_SAFE_INTEGER + 1])
def test_save_and_publish_require_an_exact_safe_integer_version(version):
    for model, value in (
        (wire.SaveDraftRequest, EXAMPLES["SaveDraftRequest"]),
        (wire.PublishWorkflowRequest, EXAMPLES["PublishWorkflowRequest"]),
    ):
        with pytest.raises(ValidationError):
            model.model_validate({**value, "expected_edit_version": version})


def test_publish_requires_a_retry_identity_and_rejects_client_revision_ids():
    value = copy.deepcopy(EXAMPLES["PublishWorkflowRequest"])
    del value["request_id"]
    with pytest.raises(ValidationError):
        wire.PublishWorkflowRequest.model_validate(value)
    with pytest.raises(ValidationError):
        wire.PublishWorkflowRequest.model_validate(
            {**EXAMPLES["PublishWorkflowRequest"], "revision_id": "client-chosen"}
        )


def test_validation_results_cannot_claim_success_with_errors():
    with pytest.raises(ValidationError, match="version_missing"):
        wire.WorkflowValidation(scope="publication", valid=True, issues=[])
    with pytest.raises(ValidationError, match="inconsistent"):
        wire.WorkflowValidation(
            valid=True, issues=[wire.ValidationIssue(code="cycle", message="循环")]
        )
    with pytest.raises(ValidationError, match="inconsistent"):
        wire.WorkflowValidation(valid=True, issues=[], truncated=True)
