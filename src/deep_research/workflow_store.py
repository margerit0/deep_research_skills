"""Persist workflow drafts and immutable revisions in the submission database.

All writes use SubmissionJournal.connection's FULL/WAL, BEGIN IMMEDIATE
transaction. The workflow migration has its own version; it does not repurpose
the submission journal's user_version.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from deep_research.submission_journal import (
    SubmissionJournal,
    get_submission_journal,
)
from deep_research.workflow_definition import (
    MAX_DOCUMENT_BYTES,
    MAX_SAFE_INTEGER,
    ArchiveWorkflowRequest,
    CreateWorkflowRequest,
    PublishWorkflowRequest,
    SaveDraftRequest,
    WireModel,
    WorkflowBinding,
    WorkflowDocument,
    WorkflowDraft,
    WorkflowPage,
    WorkflowRef,
    WorkflowRevision,
    WorkflowRevisionPage,
    WorkflowRevisionSummary,
    WorkflowSummary,
    WorkflowValidation,
    semantic_hash,
)
from deep_research.workflow_registry import standard_document
from deep_research.workflow_validation import (
    PublicationContext,
    WorkflowContractError,
    validate_document,
    verify_binding,
)

ContextProvider = Callable[[WorkflowDocument], PublicationContext]


class WorkflowStoreError(ValueError):
    """Carry safe, bounded error details across the HTTP boundary."""

    def __init__(
        self,
        reason: str,
        status: int,
        *,
        current_edit_version: int | None = None,
        validation: WorkflowValidation | None = None,
    ):
        """Keep private exceptions and document content out of public errors."""
        super().__init__(reason)
        self.reason = reason
        self.status = status
        self.current_edit_version = current_edit_version
        self.validation = validation

    def payload(self) -> dict:
        """Return the public conflict or validation envelope."""
        result = {"reason": self.reason}
        if self.current_edit_version is not None:
            result["current_edit_version"] = self.current_edit_version
        if self.validation is not None:
            result["validation"] = self.validation.model_dump(mode="json")
        return result


def _json(value) -> str:
    if isinstance(value, WireModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _document(value: WorkflowDocument) -> WorkflowDocument:
    # Reparse even model instances: assignment can bypass Pydantic validation.
    try:
        raw = _json(value)
        if len(raw.encode("utf-8")) > MAX_DOCUMENT_BYTES:
            raise WorkflowStoreError("workflow_document_too_large", 400)
        return WorkflowDocument.model_validate_json(raw)
    except (ValidationError, TypeError, ValueError, RecursionError) as exc:
        if isinstance(exc, WorkflowStoreError):
            raise
        raise WorkflowStoreError("workflow_request_invalid", 400) from exc


def _increment(version: int) -> int:
    if version >= MAX_SAFE_INTEGER:
        raise WorkflowStoreError("workflow_version_exhausted", 503)
    return version + 1


def _migrate(db: sqlite3.Connection) -> None:
    """Apply the additive migration inside the caller's existing transaction."""
    db.execute(
        "CREATE TABLE IF NOT EXISTS workflow_schema (singleton INTEGER PRIMARY KEY CHECK(singleton=1), version INTEGER NOT NULL)"
    )
    row = db.execute("SELECT version FROM workflow_schema WHERE singleton=1").fetchone()
    if row is not None:
        if row[0] not in (1, 2):
            raise WorkflowStoreError("workflow_storage_incompatible", 503)
        if row[0] == 1:
            _migrate_execution(db)
        return
    # Do not use executescript: it commits the surrounding transaction early.
    statements = (
        """CREATE TABLE workflows (
            workflow_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, archived_at TEXT
        )""",
        """CREATE TABLE workflow_revisions (
            workflow_id TEXT NOT NULL REFERENCES workflows(workflow_id),
            revision_id TEXT NOT NULL UNIQUE,
            revision_number INTEGER NOT NULL CHECK(revision_number>0),
            source_edit_version INTEGER NOT NULL,
            revision TEXT NOT NULL, content_hash TEXT NOT NULL,
            PRIMARY KEY(workflow_id, revision_id),
            UNIQUE(workflow_id, revision_number)
        )""",
        """CREATE TABLE workflow_drafts (
            workflow_id TEXT PRIMARY KEY REFERENCES workflows(workflow_id),
            edit_version INTEGER NOT NULL CHECK(edit_version>0), base_revision_id TEXT,
            document TEXT NOT NULL, updated_at TEXT NOT NULL,
            FOREIGN KEY(workflow_id, base_revision_id)
                REFERENCES workflow_revisions(workflow_id, revision_id)
        )""",
        """CREATE TABLE workflow_create_requests (
            request_id TEXT PRIMARY KEY, request TEXT NOT NULL,
            workflow_id TEXT NOT NULL REFERENCES workflows(workflow_id),
            response TEXT NOT NULL
        )""",
        """CREATE TABLE workflow_publish_requests (
            request_id TEXT PRIMARY KEY, request TEXT NOT NULL,
            workflow_id TEXT NOT NULL, revision_id TEXT NOT NULL,
            FOREIGN KEY(workflow_id, revision_id)
                REFERENCES workflow_revisions(workflow_id, revision_id)
        )""",
        """CREATE TABLE workflow_thread_bindings (
            thread_id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL,
            revision_id TEXT NOT NULL, binding TEXT NOT NULL,
            FOREIGN KEY(workflow_id, revision_id)
                REFERENCES workflow_revisions(workflow_id, revision_id)
        )""",
    )
    for statement in statements:
        db.execute(statement)
    for table in (
        "workflow_revisions",
        "workflow_create_requests",
        "workflow_publish_requests",
        "workflow_thread_bindings",
    ):
        for operation in ("UPDATE", "DELETE"):
            db.execute(
                f"CREATE TRIGGER {table}_no_{operation.lower()} BEFORE {operation} ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'immutable_workflow_record'); END"
            )
    db.execute("INSERT INTO workflow_schema VALUES (1, 1)")
    _migrate_execution(db)


def _migrate_execution(db: sqlite3.Connection) -> None:
    """Keep per-submission binding evidence and parent events with acceptance."""
    for statement in (
        """CREATE TABLE workflow_submission_bindings (
            thread_id TEXT NOT NULL REFERENCES workflow_thread_bindings(thread_id),
            turn_id TEXT NOT NULL, binding TEXT NOT NULL,
            PRIMARY KEY(thread_id, turn_id),
            FOREIGN KEY(thread_id, turn_id) REFERENCES submissions(thread_id, turn_id)
        )""",
        """CREATE TABLE workflow_event_runs (
            run_id TEXT PRIMARY KEY REFERENCES attempts(run_id),
            journal_id TEXT NOT NULL, owner_id TEXT NOT NULL,
            last_sequence INTEGER NOT NULL DEFAULT 0,
            sealed INTEGER NOT NULL DEFAULT 0
        )""",
        """CREATE TABLE workflow_node_events (
            run_id TEXT NOT NULL REFERENCES workflow_event_runs(run_id),
            sequence INTEGER NOT NULL, event_id TEXT NOT NULL UNIQUE,
            payload TEXT NOT NULL,
            PRIMARY KEY(run_id, sequence)
        )""",
    ):
        db.execute(statement)
    for table in ("workflow_submission_bindings", "workflow_node_events"):
        for operation in ("UPDATE", "DELETE"):
            db.execute(
                f"CREATE TRIGGER {table}_no_{operation.lower()} BEFORE {operation} ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'immutable_workflow_record'); END"
            )
    db.execute("UPDATE workflow_schema SET version=2 WHERE singleton=1")


def get_workflow_store() -> WorkflowStore | None:
    """Enable local management only on the persistent submission database."""
    if os.getenv("ATLAS_WORKFLOW_EDITOR_ENABLED", "true").lower() == "false":
        return None
    journal = get_submission_journal()
    if journal is None:
        return None
    from deep_research.workflow_runtime import publication_context

    return WorkflowStore(journal, publication_context=publication_context)


class WorkflowStore:
    """Serialize edits without changing previously published documents."""

    def __init__(
        self,
        journal: SubmissionJournal | Path,
        *,
        publication_context: ContextProvider | None = None,
    ):
        """Inject explicit runtime checks; direct storage users fail closed."""
        self.journal = (
            SubmissionJournal(journal) if isinstance(journal, Path) else journal
        )
        self.publication_context = publication_context

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Join the existing journal transaction and perform additive migration."""
        with self.journal.connection() as db:
            _migrate(db)
            yield db

    def check_ready(self) -> None:
        """Verify management storage before advertising the editor capability."""
        with self.connection() as db:
            db.execute("SELECT workflow_id FROM workflow_drafts LIMIT 1").fetchone()

    @staticmethod
    def _binding(db, thread_id: str) -> WorkflowBinding | None:
        row = db.execute(
            "SELECT * FROM workflow_thread_bindings WHERE thread_id=?", (thread_id,)
        ).fetchone()
        if row is None:
            return None
        try:
            binding = WorkflowBinding.model_validate_json(row["binding"])
            if binding.thread_id != thread_id or binding.workflow_ref != WorkflowRef(
                workflow_id=row["workflow_id"], revision_id=row["revision_id"]
            ):
                raise ValueError("Binding index mismatch")
            return binding
        except (TypeError, ValueError) as exc:
            raise WorkflowContractError("workflow_binding_mismatch") from exc

    @staticmethod
    def submission_binding(db, thread_id, turn_id) -> WorkflowBinding | None:
        """Read independent evidence so losing a binding cannot select the old graph."""
        row = db.execute(
            "SELECT binding FROM workflow_submission_bindings WHERE thread_id=? AND turn_id=?",
            (thread_id, turn_id),
        ).fetchone()
        binding = WorkflowStore._binding(db, thread_id)
        if row is None:
            if binding is not None:
                raise WorkflowContractError("workflow_binding_missing")
            return None
        try:
            accepted = WorkflowBinding.model_validate_json(row[0])
        except (TypeError, ValueError) as exc:
            raise WorkflowContractError("workflow_binding_mismatch") from exc
        if binding is None or binding != accepted:
            raise WorkflowContractError("workflow_binding_mismatch")
        return accepted

    @staticmethod
    def verify_record(db, record, *, for_execution=False):
        """Check accepted identity and immutable content using the caller's connection."""
        binding = WorkflowStore.submission_binding(
            db, record["thread_id"], record["turn_id"]
        )
        if binding is None:
            if record.get("workflow_binding") or record["payload"].get("workflow_ref"):
                raise WorkflowContractError("workflow_binding_missing")
            return None
        if binding.model_dump(mode="json") != record.get("workflow_binding"):
            raise WorkflowContractError("workflow_binding_mismatch")
        reference = binding.workflow_ref
        revision = WorkflowStore._revision(
            db, reference.workflow_id, reference.revision_id
        )
        requested = record["payload"].get("workflow_ref")
        verify_binding(
            binding,
            revision,
            thread_id=record["thread_id"],
            requested_ref=WorkflowRef.model_validate(requested) if requested else None,
            for_execution=for_execution,
        )
        return binding, revision

    def resolve(self, thread_id, *, requested_ref=None, for_execution=False):
        """Resolve an existing thread without inferring a default or latest version."""
        with self.connection() as db:
            binding = self._binding(db, thread_id)
            if binding is None:
                raise WorkflowContractError("workflow_binding_missing")
            reference = binding.workflow_ref
            revision = self._revision(db, reference.workflow_id, reference.revision_id)
            verify_binding(
                binding,
                revision,
                thread_id=thread_id,
                requested_ref=requested_ref,
                for_execution=for_execution,
            )
            return binding, revision

    def selection(self, thread_id, requested_ref, *, has_history):
        """Prepare a candidate; this read never persists a thread binding."""
        with self.connection() as db:
            binding = self._binding(db, thread_id)
            if binding is None:
                if requested_ref is None:
                    return None
                if (
                    has_history
                    or db.execute(
                        "SELECT 1 FROM submissions WHERE thread_id=? LIMIT 1",
                        (thread_id,),
                    ).fetchone()
                ):
                    raise WorkflowContractError("legacy_workflow_locked")
                if self._row(db, requested_ref.workflow_id)["archived_at"] is not None:
                    raise WorkflowStoreError("workflow_archived", 409)
                revision = self._revision(
                    db, requested_ref.workflow_id, requested_ref.revision_id
                )
                binding = WorkflowBinding(
                    thread_id=thread_id,
                    workflow_ref=requested_ref,
                    semantic_hash=revision.semantic_hash,
                    compatibility=revision.compatibility,
                    bound_at=_now(),
                )
            else:
                reference = binding.workflow_ref
                revision = self._revision(
                    db, reference.workflow_id, reference.revision_id
                )
            verify_binding(
                binding,
                revision,
                thread_id=thread_id,
                requested_ref=requested_ref,
                for_execution=True,
            )
            return binding, revision

    def accept(
        self, thread_id, turn_id, payload, configuration, candidate, *, has_history
    ):
        """Commit binding, configuration, payload and fixed run UUID atomically."""
        from deep_research.submission_journal import SubmissionConflict, digest
        from deep_research.workflow_runtime import require_executable

        with self.connection() as db:
            prior = db.execute(
                "SELECT payload_hash FROM submissions WHERE thread_id=? AND turn_id=?",
                (thread_id, turn_id),
            ).fetchone()
            if prior:
                if prior[0] != digest(payload):
                    raise SubmissionConflict("submission_payload_conflict")
                return self.journal.get_in_connection(db, thread_id, turn_id)
            bound = self._binding(db, thread_id)
            if candidate is None:
                if bound is not None:
                    raise WorkflowContractError("workflow_binding_conflict")
            else:
                binding, checked_revision = candidate
                reference = binding.workflow_ref
                revision = self._revision(
                    db, reference.workflow_id, reference.revision_id
                )
                if revision != checked_revision:
                    raise WorkflowContractError("workflow_archive_invalid")
                verify_binding(
                    binding, revision, thread_id=thread_id, for_execution=True
                )
                require_executable(revision)
                if bound is not None and bound != binding:
                    raise WorkflowContractError("workflow_binding_conflict")
                if bound is None:
                    if (
                        has_history
                        or db.execute(
                            "SELECT 1 FROM submissions WHERE thread_id=? LIMIT 1",
                            (thread_id,),
                        ).fetchone()
                    ):
                        raise WorkflowContractError("legacy_workflow_locked")
                    if self._row(db, reference.workflow_id)["archived_at"] is not None:
                        raise WorkflowStoreError("workflow_archived", 409)
                    db.execute(
                        "INSERT INTO workflow_thread_bindings VALUES (?, ?, ?, ?)",
                        (
                            thread_id,
                            reference.workflow_id,
                            reference.revision_id,
                            _json(binding),
                        ),
                    )
                if configuration is None:
                    raise WorkflowContractError("workflow_configuration_missing")
            self.journal.reserve_in_connection(
                db, thread_id, turn_id, payload, configuration
            )
            if candidate is not None:
                db.execute(
                    "INSERT INTO workflow_submission_bindings VALUES (?, ?, ?)",
                    (thread_id, turn_id, _json(candidate[0])),
                )
            return self.journal.get_in_connection(db, thread_id, turn_id)

    @staticmethod
    def _row(db, workflow_id: str):
        row = db.execute(
            "SELECT w.*, d.edit_version, d.base_revision_id, d.document, d.updated_at "
            "FROM workflows w JOIN workflow_drafts d USING(workflow_id) WHERE w.workflow_id=?",
            (workflow_id,),
        ).fetchone()
        if row is None:
            raise WorkflowStoreError("workflow_not_found", 404)
        return row

    @staticmethod
    def _draft(row) -> WorkflowDraft:
        try:
            document = _document(WorkflowDocument.model_validate_json(row["document"]))
            return WorkflowDraft(
                workflow_id=row["workflow_id"],
                edit_version=row["edit_version"],
                base_revision_id=row["base_revision_id"],
                document=document,
                updated_at=row["updated_at"],
            )
        except (ValueError, TypeError) as exc:
            raise WorkflowStoreError("workflow_archive_invalid", 503) from exc

    @staticmethod
    def _editable(row, expected: int) -> None:
        if row["archived_at"] is not None:
            raise WorkflowStoreError("workflow_archived", 409)
        if row["edit_version"] != expected:
            raise WorkflowStoreError(
                "workflow_edit_conflict", 409, current_edit_version=row["edit_version"]
            )

    @staticmethod
    def _revision(db, workflow_id: str, revision_id: str) -> WorkflowRevision:
        row = db.execute(
            "SELECT * FROM workflow_revisions WHERE workflow_id=? AND revision_id=?",
            (workflow_id, revision_id),
        ).fetchone()
        if row is None:
            raise WorkflowStoreError("workflow_revision_not_found", 404)
        try:
            revision = WorkflowRevision.model_validate_json(row["revision"])
            if (
                revision.workflow_id != workflow_id
                or revision.revision_id != revision_id
                or revision.revision_number != row["revision_number"]
                or revision.source_edit_version != row["source_edit_version"]
                or _hash(row["revision"]) != row["content_hash"]
            ):
                raise ValueError("Archive metadata mismatch")
            _document(revision.document)
            return revision
        except (ValueError, TypeError) as exc:
            raise WorkflowStoreError("workflow_archive_invalid", 503) from exc

    @staticmethod
    def _revision_summary(revision: WorkflowRevision) -> WorkflowRevisionSummary:
        return WorkflowRevisionSummary.model_validate(
            revision.model_dump(include=set(WorkflowRevisionSummary.model_fields))
        )

    def _summary(self, db, row) -> WorkflowSummary:
        draft = self._draft(row)
        latest = db.execute(
            "SELECT revision_id FROM workflow_revisions WHERE workflow_id=? ORDER BY revision_number DESC LIMIT 1",
            (draft.workflow_id,),
        ).fetchone()
        return WorkflowSummary(
            workflow_id=draft.workflow_id,
            name=draft.document.name,
            archived=row["archived_at"] is not None,
            edit_version=draft.edit_version,
            base_revision_id=draft.base_revision_id,
            latest_revision=self._revision_summary(
                self._revision(db, draft.workflow_id, latest[0])
            )
            if latest
            else None,
            created_at=row["created_at"],
            updated_at=draft.updated_at,
        )

    def create(self, request: CreateWorkflowRequest) -> WorkflowDraft:
        """Create one new identity, or replay the original creation receipt."""
        encoded = _json(request)
        with self.connection() as db:
            prior = db.execute(
                "SELECT * FROM workflow_create_requests WHERE request_id=?",
                (request.request_id,),
            ).fetchone()
            if prior is not None:
                if prior["request"] != encoded:
                    raise WorkflowStoreError("workflow_request_conflict", 409)
                return WorkflowDraft.model_validate_json(prior["response"])
            source = request.source
            if source.kind == "template":
                document = standard_document(request.name)
            elif source.kind == "import":
                document = source.document.model_copy(deep=True)
            else:
                document = self._revision(
                    db, source.workflow_ref.workflow_id, source.workflow_ref.revision_id
                ).document.model_copy(deep=True)
            document.name = request.name
            document = _document(document)
            draft = WorkflowDraft(
                workflow_id=f"workflow_{uuid4().hex}",
                edit_version=1,
                document=document,
                updated_at=_now(),
            )
            db.execute(
                "INSERT INTO workflows VALUES (?, ?, NULL)",
                (draft.workflow_id, draft.updated_at),
            )
            db.execute(
                "INSERT INTO workflow_drafts VALUES (?, 1, NULL, ?, ?)",
                (draft.workflow_id, _json(document), draft.updated_at),
            )
            db.execute(
                "INSERT INTO workflow_create_requests VALUES (?, ?, ?, ?)",
                (request.request_id, encoded, draft.workflow_id, _json(draft)),
            )
            return draft

    def get(self, workflow_id: str) -> WorkflowDraft:
        """Read a draft without implicitly creating or updating it."""
        with self.connection() as db:
            return self._draft(self._row(db, workflow_id))

    def summary(self, workflow_id: str) -> WorkflowSummary:
        """Read archive state alongside the draft and publication references."""
        with self.connection() as db:
            return self._summary(db, self._row(db, workflow_id))

    def save(self, workflow_id: str, request: SaveDraftRequest) -> WorkflowDraft:
        """Save the full document only if its baseline edit version still matches."""
        document = _document(request.document)
        with self.connection() as db:
            row = self._row(db, workflow_id)
            self._editable(row, request.expected_edit_version)
            db.execute(
                "UPDATE workflow_drafts SET edit_version=?, document=?, updated_at=? WHERE workflow_id=?",
                (_increment(row["edit_version"]), _json(document), _now(), workflow_id),
            )
            return self._draft(self._row(db, workflow_id))

    def _validate(self, draft: WorkflowDraft) -> WorkflowValidation:
        if self.publication_context is None:
            raise WorkflowStoreError("workflow_runtime_unavailable", 503)
        context = self.publication_context(draft.document.model_copy(deep=True))
        if not isinstance(context, PublicationContext):
            raise WorkflowStoreError("workflow_runtime_unavailable", 503)
        return validate_document(
            draft.document, checked_edit_version=draft.edit_version, context=context
        )

    def validate(
        self, workflow_id: str, expected_edit_version: int
    ) -> WorkflowValidation:
        """Validate the exact saved snapshot, outside the write transaction."""
        with self.connection() as db:
            row = self._row(db, workflow_id)
            self._editable(row, expected_edit_version)
            draft = self._draft(row)
        return self._validate(draft)

    def _prior_publication(self, db, workflow_id: str, request: PublishWorkflowRequest):
        prior = db.execute(
            "SELECT * FROM workflow_publish_requests WHERE request_id=?",
            (request.request_id,),
        ).fetchone()
        if prior is None:
            return None
        if prior["workflow_id"] != workflow_id or prior["request"] != _json(request):
            raise WorkflowStoreError("workflow_request_conflict", 409)
        return self._revision(db, workflow_id, prior["revision_id"])

    def publish(
        self, workflow_id: str, request: PublishWorkflowRequest
    ) -> WorkflowRevision:
        """Publish atomically, consulting durable retries before version checks."""
        with self.connection() as db:
            prior = self._prior_publication(db, workflow_id, request)
            if prior is not None:
                return prior
            row = self._row(db, workflow_id)
            self._editable(row, request.expected_edit_version)
            draft = self._draft(row)
        validation = self._validate(draft)
        if not validation.valid:
            raise WorkflowStoreError(
                "workflow_validation_failed", 422, validation=validation
            )
        with self.connection() as db:
            prior = self._prior_publication(db, workflow_id, request)
            if prior is not None:
                return prior
            row = self._row(db, workflow_id)
            self._editable(row, request.expected_edit_version)
            if _json(self._draft(row).document) != _json(draft.document):
                raise WorkflowStoreError(
                    "workflow_edit_conflict",
                    409,
                    current_edit_version=row["edit_version"],
                )
            last = db.execute(
                "SELECT COALESCE(MAX(revision_number), 0) FROM workflow_revisions WHERE workflow_id=?",
                (workflow_id,),
            ).fetchone()[0]
            # A valid publication context has the same supported compatibility.
            from deep_research.workflow_registry import COMPATIBILITY

            revision = WorkflowRevision(
                workflow_id=workflow_id,
                revision_id=f"revision_{uuid4().hex}",
                revision_number=_increment(last),
                source_edit_version=draft.edit_version,
                semantic_hash=semantic_hash(draft.document.definition),
                compatibility=COMPATIBILITY,
                document=draft.document,
                note=request.note,
                published_at=_now(),
            )
            encoded = _json(revision)
            db.execute(
                "INSERT INTO workflow_revisions VALUES (?, ?, ?, ?, ?, ?)",
                (
                    workflow_id,
                    revision.revision_id,
                    revision.revision_number,
                    draft.edit_version,
                    encoded,
                    _hash(encoded),
                ),
            )
            db.execute(
                "INSERT INTO workflow_publish_requests VALUES (?, ?, ?, ?)",
                (request.request_id, _json(request), workflow_id, revision.revision_id),
            )
            db.execute(
                "UPDATE workflow_drafts SET edit_version=?, base_revision_id=?, updated_at=? WHERE workflow_id=?",
                (
                    _increment(draft.edit_version),
                    revision.revision_id,
                    revision.published_at,
                    workflow_id,
                ),
            )
            return revision

    def revision(self, workflow_id: str, revision_id: str) -> WorkflowRevision:
        """Read the original snapshot even if the workflow has been archived."""
        with self.connection() as db:
            return self._revision(db, workflow_id, revision_id)

    @staticmethod
    def _page(after: int, limit: int) -> None:
        if (
            type(after) is not int
            or type(limit) is not int
            or not 0 <= after <= MAX_SAFE_INTEGER
            or not 1 <= limit <= 100
        ):
            raise WorkflowStoreError("workflow_page_invalid", 400)

    def list(
        self, *, archived: str = "active", after: int = 0, limit: int = 30
    ) -> WorkflowPage:
        """Page by creation order so saving a draft cannot skip a list item."""
        self._page(after, limit)
        if archived not in {"active", "archived", "all"}:
            raise WorkflowStoreError("workflow_page_invalid", 400)
        with self.connection() as db:
            rows = db.execute(
                "SELECT rowid, workflow_id FROM workflows WHERE (?=0 OR rowid<?) "
                "AND (?='all' OR (?='archived')=(archived_at IS NOT NULL)) ORDER BY rowid DESC LIMIT ?",
                (after, after, archived, archived, limit + 1),
            ).fetchall()
            return WorkflowPage(
                items=[
                    self._summary(db, self._row(db, row["workflow_id"]))
                    for row in rows[:limit]
                ],
                next_cursor=rows[limit - 1]["rowid"] if len(rows) > limit else None,
            )

    def revisions(
        self, workflow_id: str, *, after: int = 0, limit: int = 30
    ) -> WorkflowRevisionPage:
        """List publication summaries without modifying the current draft."""
        self._page(after, limit)
        with self.connection() as db:
            self._row(db, workflow_id)
            rows = db.execute(
                "SELECT revision_id, revision_number FROM workflow_revisions WHERE workflow_id=? "
                "AND (?=0 OR revision_number<?) ORDER BY revision_number DESC LIMIT ?",
                (workflow_id, after, after, limit + 1),
            ).fetchall()
            return WorkflowRevisionPage(
                items=[
                    self._revision_summary(
                        self._revision(db, workflow_id, row["revision_id"])
                    )
                    for row in rows[:limit]
                ],
                next_cursor=rows[limit - 1]["revision_number"]
                if len(rows) > limit
                else None,
            )

    def archive(
        self, workflow_id: str, request: ArchiveWorkflowRequest
    ) -> WorkflowSummary:
        """Keep every draft, revision and binding while closing future edits."""
        with self.connection() as db:
            row = self._row(db, workflow_id)
            if row["archived_at"] is None:
                self._editable(row, request.expected_edit_version)
                db.execute(
                    "UPDATE workflows SET archived_at=? WHERE workflow_id=?",
                    (_now(), workflow_id),
                )
            return self._summary(db, self._row(db, workflow_id))
