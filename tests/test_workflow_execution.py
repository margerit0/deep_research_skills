"""M3 real-node semantics, atomic acceptance and durable parent event checks."""

import asyncio
import inspect
import json
import sqlite3
import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from langgraph.types import Command, Overwrite

from deep_research import structured_output_fallback, workflow_events, workflow_runtime
from deep_research.submission_journal import SubmissionConflict, digest, state_digest
from deep_research.workflow_compiler import compile_workflow
from deep_research.workflow_definition import (
    ArchiveWorkflowRequest,
    EdgeDefinition,
    NodeDefinition,
    SaveDraftRequest,
    WorkflowBinding,
    WorkflowRef,
)
from deep_research.workflow_nodes import adapt_result, implementations
from deep_research.workflow_registry import COMPATIBILITY, standard_document
from deep_research.workflow_store import WorkflowStore, WorkflowStoreError
from deep_research.workflow_validation import WorkflowContractError
from tests import test_full_workflow as full_fixture
from tests.test_full_workflow import request, worker
from tests.test_workflow_store import create, publication, publication_context


@pytest.fixture(name="harness")
def real_nodes():
    yield from full_fixture.harness.__wrapped__()


def document(*, clarify=True, extensions=1):
    value = standard_document()
    nodes = {node.id: node for node in value.definition.nodes}
    path = [
        "start",
        "prepare_research",
        *(["clarify_with_user"] if clarify else []),
        "write_research_brief",
    ]
    for index in range(extensions):
        name = f"plan_{index}"
        nodes[name] = NodeDefinition(
            id=name,
            type="optimize_plan",
            parameters={"instructions": "保留 {literal} 原要求"},
        )
        path.append(name)
    path.append("supervisor_subgraph")
    for index in range(extensions):
        name = f"notes_{index}"
        nodes[name] = NodeDefinition(
            id=name,
            type="organize_notes",
            parameters={"instructions": "整理 ${literal} 材料"},
        )
        path.append(name)
    path += ["final_report_generation", "end"]
    value.definition.nodes = [nodes[name] for name in path]
    value.definition.edges = [
        EdgeDefinition(id=f"edge_{index}", source=a, target=b)
        for index, (a, b) in enumerate(zip(path, path[1:]))
    ]
    return value


def binding_for(revision, thread=None):
    return WorkflowBinding(
        thread_id=thread or str(uuid4()),
        workflow_ref=WorkflowRef(
            workflow_id=revision.workflow_id, revision_id=revision.revision_id
        ),
        semantic_hash=revision.semantic_hash,
        compatibility=COMPATIBILITY,
        bound_at=datetime.now(UTC).isoformat(),
    )


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_SUBMISSION_DB", str(tmp_path / "submissions.sqlite3"))
    monkeypatch.setenv("ATLAS_CONFIG_DB", str(tmp_path / "configs.sqlite3"))
    monkeypatch.setenv("LANGGRAPH_DISABLE_FILE_PERSISTENCE", "false")
    monkeypatch.setenv("ATLAS_SUBMISSIONS_ENABLED", "true")
    monkeypatch.setenv("ATLAS_WORKFLOW_EXECUTION_ENABLED", "true")
    return WorkflowStore(
        tmp_path / "submissions.sqlite3", publication_context=publication_context
    )


def publish(store, value=None):
    draft = create(store)
    if value is not None:
        draft = store.save(
            draft.workflow_id, SaveDraftRequest(expected_edit_version=1, document=value)
        )
    return store.publish(draft.workflow_id, publication(draft))


def accept(
    store, revision, *, thread=None, turn=None, explicit=True, configuration=None
):
    thread, turn = thread or str(uuid4()), turn or str(uuid4())
    reference = WorkflowRef(
        workflow_id=revision.workflow_id, revision_id=revision.revision_id
    )
    payload = {
        "research_id": str(uuid4()),
        "text": "Question",
        "expected_turn_id": None,
    }
    if explicit:
        payload["workflow_ref"] = reference.model_dump()
    candidate = store.selection(
        thread, reference if explicit else None, has_history=False
    )
    record = store.accept(
        thread,
        turn,
        payload,
        configuration or {"fixture": True},
        candidate,
        has_history=False,
    )
    return record


@pytest.mark.parametrize(
    "clarify,extensions", [(True, 0), (True, 1), (False, 1), (False, 2)]
)
def test_real_nodes_execute_the_exact_published_chain(
    harness, store, monkeypatch, clarify, extensions
):
    value = document(clarify=clarify, extensions=extensions)
    revision = publish(store, value)
    binding = binding_for(revision)
    calls, events, optimized, organized = [], [], [], []

    def optimize(_model, schema, prompt):
        assert "{literal}" in prompt
        optimized.append(prompt)
        return schema(research_brief=f"Optimized brief {len(optimized)}")

    def organize(messages):
        assert "${literal}" in messages[-1].content
        if organized:
            assert organized[-1] in messages[-1].content
        organized.append(f"Organized material {len(organized) + 1} [1]")
        return AIMessage(content=organized[-1])

    monkeypatch.setattr(
        structured_output_fallback, "invoke_with_structured_output_fallback", optimize
    )
    monkeypatch.setattr(worker, "compress_model", SimpleNamespace(invoke=organize))
    handlers = {}
    for key, original in implementations().items():

        def wrap(key, original):
            async def invoke(state, **kwargs):
                calls.append(key[0])
                if key[0] == "supervisor_subgraph" and extensions:
                    assert state["research_brief"] == f"Optimized brief {extensions}"
                    assert len(state["supervisor_messages"]) == 1
                    assert (
                        state["supervisor_messages"][0].content
                        == state["research_brief"]
                    )
                return (
                    await original(state, **kwargs)
                    if inspect.iscoroutinefunction(original)
                    else original(state, **kwargs)
                )

            return invoke

        handlers[key] = wrap(key, original)
    graph = compile_workflow(
        value,
        binding=binding,
        handlers=handlers,
        event_sink=lambda _config, _binding, node, kind, _elapsed, **_kw: events.append(
            (node.id, kind)
        ),
    )
    result = asyncio.run(graph.ainvoke(request("Question", "study", "turn")))
    assert result["research_status"] == "succeeded", result["research_errors"]
    assert calls == [
        n.type for n in value.definition.nodes if n.type not in {"start", "end"}
    ]
    assert [name for name, kind in events if kind == "completed"] == [
        n.id for n in value.definition.nodes[1:-1]
    ]
    assert result["workflow_binding"] == binding.model_dump(mode="json")
    assert result["notes"] == ["Valid finding [1]"] and result["raw_notes"] == ["Raw A"]
    assert len(result["sources"]) == 1
    assert result["organized_notes"] == (organized[-1] if extensions else None)
    if extensions:
        assert organized[-1] in harness.writer.call_args.args[0][-1].content
    assert len(optimized) == len(organized) == extensions
    assert harness.writer.await_count == harness.researcher.await_count == 1


@pytest.mark.parametrize("point", ["plan", "notes", "findings"])
def test_failed_extensions_or_missing_material_do_not_produce_reports(
    harness, store, monkeypatch, point
):
    value = document()
    revision = publish(store, value)
    monkeypatch.setattr(
        structured_output_fallback,
        "invoke_with_structured_output_fallback",
        lambda _m, schema, _p: schema(
            research_brief="" if point == "plan" else "Optimized"
        ),
    )
    monkeypatch.setattr(
        worker,
        "compress_model",
        SimpleNamespace(invoke=lambda _: AIMessage(content="")),
    )
    if point == "findings":
        harness.researcher.return_value["compressed_research"] = ""
    graph = compile_workflow(
        value, binding=binding_for(revision), event_sink=lambda *_a, **_kw: None
    )
    result = asyncio.run(graph.ainvoke(request("Question", "study", "turn")))
    assert result["research_status"] == "failed" and not result["final_report"]
    harness.writer.assert_not_awaited()
    if point == "notes":
        assert (
            result["notes"] and result["sources"] and result["organized_notes"] is None
        )
    if point == "plan":
        harness.researcher.assert_not_awaited()


def test_adapter_strips_routes_and_enforces_writable_fields():
    core = NodeDefinition(id="write_research_brief", type="write_research_brief")
    result = adapt_result(
        core, Command(goto="supervisor_subgraph", update={"supervisor_messages": []})
    )
    assert result.result.outcome == "continue"
    assert isinstance(result.update["supervisor_messages"], Overwrite)
    extension = NodeDefinition(id="plan_1", type="optimize_plan")
    for update in (
        {"sources": []},
        {"workflow_binding": {}},
        {"research_brief": Overwrite("bad")},
    ):
        with pytest.raises(WorkflowContractError):
            adapt_result(extension, update)
    with pytest.raises(WorkflowContractError, match="route_invalid"):
        adapt_result(core, Command(goto=["a", "b"], update={}))


@pytest.mark.parametrize(
    "table",
    [
        "submissions",
        "attempts",
        "submission_configurations",
        "workflow_submission_bindings",
    ],
)
def test_acceptance_fault_rolls_back_binding_configuration_and_run(store, table):
    revision = publish(store)
    with store.connection() as db:
        db.execute(
            f"CREATE TRIGGER fixture_fault BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT, 'fixture_fault'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="fixture_fault"):
        accept(store, revision)
    with store.connection() as db:
        for name in (
            "workflow_thread_bindings",
            "workflow_submission_bindings",
            "submissions",
            "attempts",
            "submission_configurations",
        ):
            assert db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] == 0


def test_binding_is_permanent_and_omitted_reference_preserves_payload_digest(store):
    first, second = publish(store), publish(store, document(clarify=False))
    record = accept(store, first)
    bound = record["workflow_binding"]
    thread = record["thread_id"]
    store.archive(
        first.workflow_id,
        ArchiveWorkflowRequest(
            expected_edit_version=store.get(first.workflow_id).edit_version
        ),
    )
    continued = accept(store, first, thread=thread, explicit=False)
    assert continued["workflow_binding"] == bound
    assert "workflow_ref" not in continued["payload"]
    assert continued["payload_hash"] == digest(continued["payload"])
    with pytest.raises(WorkflowContractError, match="binding_conflict"):
        accept(store, second, thread=thread)
    with pytest.raises(WorkflowStoreError, match="workflow_archived"):
        accept(store, first)
    with store.connection() as db:
        assert (
            db.execute("SELECT COUNT(*) FROM workflow_thread_bindings").fetchone()[0]
            == 1
        )
    replay = store.accept(
        thread, record["turn_id"], record["payload"], None, None, has_history=True
    )
    assert replay == record
    with pytest.raises(SubmissionConflict):
        store.accept(
            thread,
            record["turn_id"],
            {**record["payload"], "text": "other"},
            None,
            None,
            has_history=True,
        )


def test_legacy_thread_cannot_bind_even_if_native_history_is_missing(store):
    revision = publish(store)
    thread = str(uuid4())
    store.journal.reserve(thread, str(uuid4()), {"research_id": "old", "text": "old"})
    with pytest.raises(WorkflowContractError, match="legacy_workflow_locked"):
        accept(store, revision, thread=thread)


def test_missing_implementation_keeps_original_archive_readable(store, monkeypatch):
    revision = publish(store, document())
    record = accept(store, revision)
    original = implementations()
    original.pop(("optimize_plan", 1))
    monkeypatch.setattr(workflow_runtime, "implementations", lambda: original)
    with pytest.raises(WorkflowContractError, match="implementation_unavailable"):
        workflow_runtime.validate_record(record, for_execution=True)
    assert workflow_runtime.validate_record(record)[1] == revision
    graph = workflow_runtime.graph(
        {"configurable": {"thread_id": record["thread_id"]}},
        SimpleNamespace(access_context="threads.read"),
    )
    assert "plan_0" in graph.get_graph().nodes
    with pytest.raises(WorkflowContractError, match="observation_only"):
        asyncio.run(graph.ainvoke({}))


def test_optional_state_fields_do_not_change_legacy_recovery_digest():
    state = {"messages": [], "notes": ["same"]}
    baseline = state_digest(state)
    # Calculated by the unmodified state_digest at the M2 commit 574e655.
    assert (
        baseline == "961e82ac251dd6389c0f2c91521ceee0e25d829fcc1b0fc6930d96e2fdb35f4e"
    )
    assert baseline == state_digest(json.loads(json.dumps(state)))
    assert state_digest({**state, "organized_notes": None}) != baseline
    assert state_digest({**state, "workflow_binding": {}}) != baseline


def test_parent_events_commit_before_delivery_and_reject_wrong_identity(
    store, monkeypatch
):
    revision = publish(store)
    record = accept(store, revision)
    attempt = record["attempts"][0]
    binding = WorkflowBinding.model_validate(record["workflow_binding"])
    config = {
        "configurable": {"thread_id": record["thread_id"], "run_id": attempt["run_id"]},
        "metadata": {
            "atlas_submission_version": 1,
            "atlas_research_id": record["research_id"],
            "atlas_turn_id": record["turn_id"],
            "atlas_attempt_id": attempt["attempt_id"],
        },
    }
    store.journal.enter_node(
        attempt["run_id"], record["thread_id"], "prepare_research", {}
    )
    delivered = []

    def deliver(envelope):
        with store.connection() as db:
            assert (
                db.execute("SELECT COUNT(*) FROM workflow_node_events").fetchone()[0]
                == envelope["event"]["sequence"]
            )
        delivered.append(envelope["event"])

    monkeypatch.setattr(workflow_events, "get_stream_writer", lambda: deliver)
    node = revision.document.definition.nodes[1]
    workflow_events.append_event(config, binding, node, "started", 0)
    workflow_events.append_event(config, binding, node, "completed", 3, terminal=True)
    args = (
        record["thread_id"],
        attempt["run_id"],
        record["research_id"],
        record["turn_id"],
        attempt["attempt_id"],
    )
    page = workflow_events.read_events(*args, limit=1)
    assert page["events"] == delivered[:1] and page["has_more"] and page["sealed"]
    assert workflow_events.read_events(*args, after=1)["events"] == delivered[1:]
    with pytest.raises(WorkflowContractError, match="identity_mismatch"):
        workflow_events.read_events(*args[:2], "other", *args[3:])
    with pytest.raises(WorkflowContractError, match="sequence_conflict"):
        workflow_events.append_event(config, binding, node, "started", 0)


def test_publication_context_is_built_from_real_implementations(store):
    context = workflow_runtime.publication_context(document())
    assert {"optimize_plan", "organize_notes"} <= context.implemented_types
    assert set(context.default_selection.models) == {
        "SCOPING",
        "SUPERVISOR",
        "RESEARCHER",
        "SUMMARIZATION",
        "COMPRESSION",
        "FINAL_REPORT",
    }
    actual = WorkflowStore(
        store.journal, publication_context=workflow_runtime.publication_context
    )
    draft = create(actual)
    assert actual.validate(draft.workflow_id, draft.edit_version).valid
    assert actual.publish(draft.workflow_id, publication(draft)).revision_number == 1


@pytest.mark.parametrize("short", [False, True])
def test_writer_uses_organized_material_even_with_complete_source_evidence(
    harness, store, monkeypatch, short
):
    from deep_research.source_evidence import (
        capture_source_evidence,
        record_source_evidence,
    )
    from tests.test_full_workflow import SOURCE

    with capture_source_evidence() as evidence:
        record_source_evidence(
            SOURCE["url"],
            {"raw_content": "Original source evidence under condition A."},
        )
    harness.researcher.return_value["source_evidence"] = evidence
    monkeypatch.setattr(
        structured_output_fallback,
        "invoke_with_structured_output_fallback",
        lambda _m, schema, _p: schema(research_brief="Organize this research"),
    )
    monkeypatch.setattr(
        worker,
        "compress_model",
        SimpleNamespace(
            invoke=lambda _: AIMessage(content="ORGANIZED DERIVED MATERIAL [1]")
        ),
    )
    value = document()
    revision = publish(store, value)
    graph = compile_workflow(
        value, binding=binding_for(revision), event_sink=lambda *_a, **_kw: None
    )
    result = asyncio.run(
        graph.ainvoke(
            request("约 500 字，回答研究问题" if short else "Question", "study", "turn")
        )
    )
    assert result["research_status"] == "succeeded", result["research_errors"]
    prompt = harness.writer.call_args.args[0][-1].content
    assert (
        "ORGANIZED DERIVED MATERIAL" in prompt and "Original source evidence" in prompt
    )
    assert result["source_evidence"] == evidence and result["notes"] == [
        "Valid finding [1]"
    ]
    assert result["raw_notes"] == ["Raw A"] and result["sources"] == [SOURCE]


@pytest.mark.parametrize("organized", ["", "   ", "## 研究未完成\nNo findings"])
def test_explicit_empty_organized_material_does_not_fall_back_to_original_notes(
    harness, organized
):
    result = asyncio.run(
        full_fixture.full.final_report_generation(
            {
                "notes": ["Valid original notes"],
                "organized_notes": organized,
            }
        )
    )
    assert (
        result["research_status"] == "failed"
        and result["research_errors"][0]["code"] == "organized_notes_empty"
    )
    harness.writer.assert_not_awaited()


def test_execution_migration_preserves_m2_revisions(store):
    revision = publish(store)
    with store.connection() as db:
        for table in (
            "workflow_node_events",
            "workflow_event_runs",
            "workflow_submission_bindings",
        ):
            db.execute(f"DROP TABLE {table}")
        db.execute("UPDATE workflow_schema SET version=1")
    store.check_ready()
    assert store.revision(revision.workflow_id, revision.revision_id) == revision
    with store.connection() as db:
        assert db.execute("SELECT version FROM workflow_schema").fetchone()[0] == 2
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_organized_material_does_not_replace_the_original_findings_gate(harness):
    result = asyncio.run(
        full_fixture.full.final_report_generation(
            {
                "notes": [],
                "organized_notes": "Derived material without original findings",
            }
        )
    )
    assert (
        result["research_status"] == "failed"
        and result["research_errors"][0]["code"] == "no_findings"
    )
    harness.writer.assert_not_awaited()


def test_only_the_registered_production_factory_advertises_execution(monkeypatch):
    from deep_research.atlas_runtime import workflow_graph_registered

    registry = {"research_workflow": lambda: None}
    monkeypatch.setitem(
        sys.modules, "langgraph_api.graph", SimpleNamespace(GRAPHS=registry)
    )
    assert not workflow_graph_registered()
    registry["research_workflow"] = workflow_runtime.graph
    assert workflow_graph_registered()
