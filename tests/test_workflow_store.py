"""M2 transaction and archive checks, with an explicit publication test context."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import pytest

from deep_research import workflow_store as module
from deep_research.workflow_definition import (
    MODEL_ROLES,
    ArchiveWorkflowRequest,
    CreateWorkflowRequest,
    NodeDefinition,
    PublishWorkflowRequest,
    SaveDraftRequest,
    TemplateSource,
    WorkflowBinding,
    WorkflowRef,
    WorkflowSelection,
    WorkflowSkills,
)
from deep_research.workflow_registry import COMPATIBILITY, node_types
from deep_research.workflow_store import WorkflowStore, WorkflowStoreError
from deep_research.workflow_validation import PublicationContext


def publication_context(document):
    """Describe test implementations only; no production compiler is claimed."""
    return PublicationContext(
        compatibility=COMPATIBILITY,
        implemented_types=frozenset(node_types()),
        model_revision_ids=frozenset({"a" * 64}),
        skill_names=frozenset({"fixture"}),
        default_selection=WorkflowSelection(
            models=dict.fromkeys(MODEL_ROLES, "a" * 64),
            skills=WorkflowSkills(mode="auto", allowed=[]),
        ),
    )


@pytest.fixture
def store(tmp_path):
    return WorkflowStore(
        tmp_path / "submissions.sqlite3", publication_context=publication_context
    )


def create(store, **kwargs):
    return store.create(
        CreateWorkflowRequest(
            request_id=str(uuid4()),
            name="行业研究",
            source=TemplateSource(kind="template", template_id="standard_research"),
            **kwargs,
        )
    )


def publication(draft, **kwargs):
    return PublishWorkflowRequest(
        request_id=str(uuid4()), expected_edit_version=draft.edit_version, **kwargs
    )


def test_migration_preserves_submissions_configuration_and_run_ids(store):
    journal = store.journal
    record = journal.reserve(
        "thread",
        "turn",
        {"research_id": "study", "text": "question"},
        {"fixture": True},
    )
    draft = create(store)
    assert journal.get("thread", "turn") == record
    restarted = WorkflowStore(journal.path)
    assert restarted.get(draft.workflow_id) == draft
    assert restarted.list().items[0].workflow_id == draft.workflow_id
    with journal.connection() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert db.execute("SELECT version FROM workflow_schema").fetchone()[0] == 2
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_partial_migration_rolls_back_all_workflow_ddl(tmp_path):
    class InterruptedConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if "CREATE TABLE workflow_publish_requests" in sql:
                raise sqlite3.OperationalError("fixture migration interruption")
            return super().execute(sql, parameters)

    path = tmp_path / "migration.sqlite3"
    db = sqlite3.connect(path, factory=InterruptedConnection)
    with pytest.raises(sqlite3.OperationalError), db:
        db.execute("BEGIN IMMEDIATE")
        module._migrate(db)
    assert (
        db.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'workflow%'"
        ).fetchall()
        == []
    )
    db.close()
    WorkflowStore(path).check_ready()


@pytest.mark.parametrize("schema", ["submission", "workflow"])
def test_unsupported_storage_version_is_not_downgraded(store, schema):
    store.check_ready()
    with store.journal.connection() as db:
        if schema == "submission":
            db.execute("PRAGMA user_version=999")
        else:
            db.execute("UPDATE workflow_schema SET version=999")
    with pytest.raises(ValueError):
        store.check_ready()
    with sqlite3.connect(store.journal.path) as db:
        query = (
            "PRAGMA user_version"
            if schema == "submission"
            else "SELECT version FROM workflow_schema"
        )
        assert db.execute(query).fetchone()[0] == 999


def test_concurrent_creation_and_retry_share_one_identity(store):
    request = CreateWorkflowRequest.model_validate(
        {
            "request_id": "create-once",
            "name": "新流程",
            "source": {"kind": "template", "template_id": "standard_research"},
        }
    )
    with ThreadPoolExecutor(max_workers=6) as pool:
        drafts = list(pool.map(lambda _: store.create(request), range(18)))
    assert len({draft.workflow_id for draft in drafts}) == 1
    assert len(store.list().items) == 1
    changed = drafts[0].document.model_copy(deep=True)
    changed.name = "之后编辑"
    store.save(
        drafts[0].workflow_id,
        SaveDraftRequest(expected_edit_version=1, document=changed),
    )
    # Retry means the original creation receipt, not another workflow or a
    # surprising response whose contents changed since the first attempt.
    assert store.create(request) == drafts[0]
    request.name = "different"
    with pytest.raises(WorkflowStoreError, match="workflow_request_conflict"):
        store.create(request)


def test_save_concurrency_has_one_winner_and_preserves_full_document(store):
    draft = create(store)
    documents = [draft.document.model_copy(deep=True) for _ in range(10)]
    for i, document in enumerate(documents):
        document.name = f"edit {i}"
        document.presentation.viewport.x = float(i)

    def save(document):
        try:
            return store.save(
                draft.workflow_id,
                SaveDraftRequest(expected_edit_version=1, document=document),
            )
        except WorkflowStoreError as exc:
            assert exc.reason == "workflow_edit_conflict"
            assert exc.current_edit_version == 2
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(save, documents))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert store.get(draft.workflow_id) == winners[0]


def test_incomplete_topology_is_saved_but_publication_is_blocked(store):
    draft = create(store)
    document = draft.document.model_copy(deep=True)
    document.definition.edges.pop()
    document.definition.nodes.append(NodeDefinition(id="future", type="future_type"))
    saved = store.save(
        draft.workflow_id, SaveDraftRequest(expected_edit_version=1, document=document)
    )
    validation = store.validate(draft.workflow_id, saved.edit_version)
    assert not validation.valid and validation.scope == "publication"
    assert validation.checked_edit_version == 2
    assert "node_type_unknown" in {issue.code for issue in validation.issues}
    with pytest.raises(WorkflowStoreError) as failed:
        store.publish(draft.workflow_id, publication(saved))
    assert failed.value.status == 422
    assert failed.value.validation == validation
    assert store.revisions(draft.workflow_id).items == []


def test_oversized_utf8_document_cannot_be_saved_or_imported(store):
    draft = create(store)
    document = draft.document.model_copy(deep=True)
    document.definition.nodes = [
        NodeDefinition(
            id=f"plan_{i}",
            type="optimize_plan",
            parameters={"instructions": "研" * 4000},
        )
        for i in range(30)
    ]
    with pytest.raises(WorkflowStoreError, match="workflow_document_too_large"):
        store.save(
            draft.workflow_id,
            SaveDraftRequest(expected_edit_version=1, document=document),
        )
    with pytest.raises(WorkflowStoreError, match="workflow_document_too_large"):
        store.create(
            CreateWorkflowRequest.model_validate(
                {
                    "request_id": "large",
                    "name": "large",
                    "source": {"kind": "import", "document": document.model_dump()},
                }
            )
        )
    assert store.get(draft.workflow_id) == draft
    assert len(store.list().items) == 1


def test_publication_snapshots_name_layout_parameters_and_draft_baseline(store):
    draft = create(store)
    draft.document.presentation.viewport.x = 133.5
    saved = store.save(
        draft.workflow_id,
        SaveDraftRequest(expected_edit_version=1, document=draft.document),
    )
    revision = store.publish(draft.workflow_id, publication(saved, note="已核对"))
    assert revision.revision_number == 1 and revision.source_edit_version == 2
    assert revision.document == saved.document
    next_draft = store.get(draft.workflow_id)
    assert (
        next_draft.edit_version == 3
        and next_draft.base_revision_id == revision.revision_id
    )
    next_draft.document.name = "新草稿"
    next_draft.document.presentation.viewport.x = 999
    store.save(
        draft.workflow_id,
        SaveDraftRequest(expected_edit_version=3, document=next_draft.document),
    )
    assert store.revision(draft.workflow_id, revision.revision_id) == revision


def test_lost_publication_response_retries_before_version_archive_or_runtime_checks(
    store,
):
    draft = create(store)
    request = publication(draft)
    first = store.publish(draft.workflow_id, request)
    current = store.get(draft.workflow_id)
    current.document.name = "later edit"
    current = store.save(
        draft.workflow_id,
        SaveDraftRequest(
            expected_edit_version=current.edit_version, document=current.document
        ),
    )
    store.archive(
        draft.workflow_id,
        ArchiveWorkflowRequest(expected_edit_version=current.edit_version),
    )
    restarted = WorkflowStore(store.journal.path)  # No currently available compiler.
    assert restarted.publish(draft.workflow_id, request) == first
    assert len(restarted.revisions(draft.workflow_id).items) == 1
    request.note = "changed retry"
    with pytest.raises(WorkflowStoreError, match="workflow_request_conflict"):
        restarted.publish(draft.workflow_id, request)


@pytest.mark.parametrize("same_request", [True, False])
def test_concurrent_publications_create_one_revision(store, same_request):
    draft = create(store)
    request = publication(draft)

    def publish(i):
        try:
            return store.publish(
                draft.workflow_id, request if same_request else publication(draft)
            )
        except WorkflowStoreError as exc:
            assert not same_request and exc.reason == "workflow_edit_conflict"
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(publish, range(12)))
    successes = [result for result in results if result is not None]
    assert len(successes) == (12 if same_request else 1)
    assert len({result.revision_id for result in successes}) == 1
    assert store.get(draft.workflow_id).edit_version == 2
    assert len(store.revisions(draft.workflow_id).items) == 1


def test_publication_rechecks_draft_after_validation_outside_transaction(store):
    draft = create(store)

    def race(document):
        document.name = "concurrent update"
        store.save(
            draft.workflow_id,
            SaveDraftRequest(expected_edit_version=1, document=document),
        )
        return publication_context(document)

    store.publication_context = race
    with pytest.raises(WorkflowStoreError, match="workflow_edit_conflict"):
        store.publish(draft.workflow_id, publication(draft))
    assert store.get(draft.workflow_id).document.name == "concurrent update"
    assert store.revisions(draft.workflow_id).items == []


def test_failed_publication_rolls_back_revision_receipt_and_baseline(store):
    draft = create(store)
    with store.connection() as db:
        db.execute(
            "CREATE TRIGGER fixture_failure BEFORE INSERT ON workflow_publish_requests BEGIN SELECT RAISE(ABORT, 'fixture interruption'); END"
        )
    request = publication(draft)
    with pytest.raises(sqlite3.IntegrityError):
        store.publish(draft.workflow_id, request)
    assert store.get(draft.workflow_id) == draft
    assert store.revisions(draft.workflow_id).items == []
    with store.connection() as db:
        assert (
            db.execute("SELECT COUNT(*) FROM workflow_publish_requests").fetchone()[0]
            == 0
        )
        db.execute("DROP TRIGGER fixture_failure")
    assert store.publish(draft.workflow_id, request).revision_number == 1


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_database_rejects_revision_mutation_even_for_presentation(store, operation):
    draft = create(store)
    store.publish(draft.workflow_id, publication(draft))
    with (
        pytest.raises(sqlite3.IntegrityError, match="immutable_workflow_record"),
        store.connection() as db,
    ):
        db.execute(
            "UPDATE workflow_revisions SET revision=revision"
            if operation == "UPDATE"
            else "DELETE FROM workflow_revisions"
        )
    assert len(store.revisions(draft.workflow_id).items) == 1


@pytest.mark.parametrize(
    "damage", ["behavior", "presentation", "identity", "compatibility", "index"]
)
def test_corrupt_archive_is_rejected_instead_of_rehashed(store, damage):
    draft = create(store)
    revision = store.publish(draft.workflow_id, publication(draft))
    with store.connection() as db:
        db.execute("DROP TRIGGER workflow_revisions_no_update")
        raw = revision.model_dump()
        if damage == "behavior":
            raw["document"]["definition"]["nodes"].pop()
        elif damage == "presentation":
            raw["document"]["presentation"]["viewport"]["x"] = 500
        elif damage == "identity":
            raw["workflow_id"] = "someone-else"
        elif damage == "compatibility":
            raw["compatibility"]["compiler_version"] = 2
        else:
            db.execute("UPDATE workflow_revisions SET revision_number=19")
        if damage != "index":
            db.execute("UPDATE workflow_revisions SET revision=?", (json.dumps(raw),))
    with pytest.raises(WorkflowStoreError, match="workflow_archive_invalid"):
        store.revision(draft.workflow_id, revision.revision_id)


def test_copy_old_revision_or_import_never_inherits_server_identity(store):
    draft = create(store)
    first = store.publish(draft.workflow_id, publication(draft))
    current = store.get(draft.workflow_id)
    current.document.name = "new baseline"
    store.save(
        draft.workflow_id,
        SaveDraftRequest(
            expected_edit_version=current.edit_version, document=current.document
        ),
    )
    for source in (
        {
            "kind": "revision",
            "workflow_ref": {
                "workflow_id": draft.workflow_id,
                "revision_id": first.revision_id,
            },
        },
        {"kind": "import", "document": first.document.model_dump()},
    ):
        copied = store.create(
            CreateWorkflowRequest.model_validate(
                {"request_id": str(uuid4()), "name": "副本", "source": source}
            )
        )
        assert copied.workflow_id != draft.workflow_id
        assert copied.base_revision_id is None and copied.edit_version == 1
        assert copied.document.definition == first.document.definition
        assert copied.document.name == "副本"
    assert store.get(draft.workflow_id).document.name == "new baseline"


def test_archive_is_idempotent_and_keeps_revisions_and_bindings(store):
    draft = create(store)
    revision = store.publish(draft.workflow_id, publication(draft))
    binding = WorkflowBinding(
        thread_id="future-thread",
        workflow_ref=WorkflowRef(
            workflow_id=draft.workflow_id, revision_id=revision.revision_id
        ),
        semantic_hash=revision.semantic_hash,
        compatibility=revision.compatibility,
        bound_at=revision.published_at,
    )
    with store.connection() as db:
        db.execute(
            "INSERT INTO workflow_thread_bindings VALUES (?, ?, ?, ?)",
            (
                binding.thread_id,
                draft.workflow_id,
                revision.revision_id,
                binding.model_dump_json(),
            ),
        )
    with pytest.raises(WorkflowStoreError, match="workflow_edit_conflict"):
        store.archive(
            draft.workflow_id, ArchiveWorkflowRequest(expected_edit_version=1)
        )
    archived = store.archive(
        draft.workflow_id, ArchiveWorkflowRequest(expected_edit_version=2)
    )
    assert archived.archived
    assert (
        store.archive(
            draft.workflow_id, ArchiveWorkflowRequest(expected_edit_version=2)
        )
        == archived
    )
    assert store.list().items == []
    assert store.list(archived="archived").items == [archived]
    assert store.revision(draft.workflow_id, revision.revision_id) == revision
    with store.connection() as db:
        assert (
            db.execute("SELECT binding FROM workflow_thread_bindings").fetchone()[0]
            == binding.model_dump_json()
        )
    with pytest.raises(WorkflowStoreError, match="workflow_archived"):
        store.save(
            draft.workflow_id,
            SaveDraftRequest(expected_edit_version=2, document=draft.document),
        )
    with pytest.raises(WorkflowStoreError, match="workflow_archived"):
        store.publish(
            draft.workflow_id,
            PublishWorkflowRequest(request_id="after-archive", expected_edit_version=2),
        )


def test_pagination_does_not_skip_on_edit_and_revision_numbers_increase(store):
    drafts = [create(store) for _ in range(5)]
    first = store.list(limit=2)
    saved = store.save(
        drafts[0].workflow_id,
        SaveDraftRequest(expected_edit_version=1, document=drafts[0].document),
    )
    second = store.list(limit=2, after=first.next_cursor)
    third = store.list(limit=2, after=second.next_cursor)
    assert [item.workflow_id for item in first.items + second.items + third.items] == [
        draft.workflow_id for draft in reversed(drafts)
    ]
    assert third.next_cursor is None
    for _ in range(5):
        store.publish(saved.workflow_id, publication(saved))
        saved = store.get(saved.workflow_id)
    page = store.revisions(saved.workflow_id, limit=2)
    assert [item.revision_number for item in page.items] == [5, 4]
    assert [
        item.revision_number
        for item in store.revisions(saved.workflow_id, after=page.next_cursor).items
    ] == [3, 2, 1]


def test_production_default_cannot_publish_with_placeholder_implementations(store):
    draft = create(store)
    production = WorkflowStore(store.journal.path)
    with pytest.raises(WorkflowStoreError, match="workflow_runtime_unavailable"):
        production.validate(draft.workflow_id, 1)
    with pytest.raises(WorkflowStoreError, match="workflow_runtime_unavailable"):
        production.publish(draft.workflow_id, publication(draft))
    store.publication_context = lambda document: replace(
        publication_context(document), implemented_types=frozenset()
    )
    assert {item.code for item in store.validate(draft.workflow_id, 1).issues} == {
        "node_implementation_unavailable"
    }
    assert store.revisions(draft.workflow_id).items == []


def test_wrong_workflow_cannot_read_or_copy_another_workflows_revision(store):
    draft, other = create(store), create(store)
    revision = store.publish(draft.workflow_id, publication(draft))
    with pytest.raises(WorkflowStoreError, match="workflow_revision_not_found"):
        store.revision(other.workflow_id, revision.revision_id)
    with pytest.raises(sqlite3.IntegrityError), store.connection() as db:
        db.execute(
            "UPDATE workflow_drafts SET base_revision_id=? WHERE workflow_id=?",
            (revision.revision_id, other.workflow_id),
        )
