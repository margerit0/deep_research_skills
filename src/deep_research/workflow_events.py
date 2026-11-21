"""Persist parent-node observations before delivering the native custom stream."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from langgraph.config import get_stream_writer
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from deep_research.event_journal import INSTANCE_ID
from deep_research.submission_journal import get_submission_journal
from deep_research.workflow_definition import MAX_SAFE_INTEGER, WorkflowNodeEvent
from deep_research.workflow_store import WorkflowStore, WorkflowStoreError
from deep_research.workflow_validation import WorkflowContractError


def _store():
    journal = get_submission_journal()
    if journal is None:
        raise WorkflowContractError("workflow_events_unavailable")
    return WorkflowStore(journal)


def _identity(db, store, thread_id, run_id):
    row = db.execute(
        "SELECT * FROM attempts WHERE thread_id=? AND run_id=?", (thread_id, run_id)
    ).fetchone()
    if row is None or row["rejected"]:
        raise WorkflowContractError("workflow_event_identity_mismatch")
    record = store.journal.get_in_connection(db, thread_id, row["turn_id"])
    resolved = store.verify_record(db, record)
    if resolved is None:
        raise WorkflowContractError("workflow_binding_missing")
    binding, revision = resolved
    for identifier in (thread_id, run_id, row["turn_id"], row["attempt_id"]):
        if str(UUID(identifier)) != identifier:
            raise WorkflowContractError("workflow_event_identity_mismatch")
    identity = {
        "thread_id": thread_id,
        "run_id": run_id,
        "research_id": record["research_id"],
        "turn_id": row["turn_id"],
        "attempt_id": row["attempt_id"],
        "workflow_ref": binding.workflow_ref.model_dump(),
        "semantic_hash": binding.semantic_hash,
    }
    return identity, revision, row


def _check_event(event, identity, revision):
    payload = event.model_dump(mode="json")
    if any(payload[key] != value for key, value in identity.items()):
        raise WorkflowContractError("workflow_event_identity_mismatch")
    node = next(
        (n for n in revision.document.definition.nodes if n.id == event.node_id), None
    )
    if node is None or node.type != event.node_type or node.type in {"start", "end"}:
        raise WorkflowContractError("workflow_event_node_mismatch")


def append_event(config, binding, node, kind, elapsed_ms, *, terminal=False):
    """Append in the acceptance database, then publish only the committed event."""
    metadata = config.get("metadata", {})
    if metadata.get("atlas_submission_version") != 1:
        return
    configurable = config.get("configurable", {})
    thread_id, run_id = (
        str(configurable.get("thread_id", "")),
        str(configurable.get("run_id", "")),
    )
    store = _store()
    with store.connection() as db:
        identity, revision, attempt = _identity(db, store, thread_id, run_id)
        if (
            attempt["owner_id"] != INSTANCE_ID
            or identity["research_id"] != metadata.get("atlas_research_id")
            or identity["turn_id"] != metadata.get("atlas_turn_id")
            or identity["attempt_id"] != metadata.get("atlas_attempt_id")
            or binding.workflow_ref.model_dump() != identity["workflow_ref"]
            or binding.semantic_hash != identity["semantic_hash"]
        ):
            raise WorkflowContractError("workflow_event_identity_mismatch")
        row = db.execute(
            "SELECT * FROM workflow_event_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            db.execute(
                "INSERT INTO workflow_event_runs (run_id, journal_id, owner_id) VALUES (?, ?, ?)",
                (run_id, str(uuid4()), INSTANCE_ID),
            )
            sequence = 1
        else:
            if row["sealed"] or row["owner_id"] != INSTANCE_ID:
                raise WorkflowContractError("workflow_event_sequence_conflict")
            sequence = row["last_sequence"] + 1
        event = WorkflowNodeEvent(
            **identity,
            id=str(uuid4()),
            sequence=sequence,
            node_id=node.id,
            node_type=node.type,
            at=datetime.now(UTC).isoformat(),
            kind=kind,
            elapsed_ms=elapsed_ms,
        )
        _check_event(event, identity, revision)
        db.execute(
            "INSERT INTO workflow_node_events VALUES (?, ?, ?, ?)",
            (run_id, sequence, event.id, event.model_dump_json()),
        )
        db.execute(
            "UPDATE workflow_event_runs SET last_sequence=?, sealed=? WHERE run_id=?",
            (sequence, int(terminal), run_id),
        )
    try:
        get_stream_writer()(
            {"type": "atlas.workflow_event", "event": event.model_dump(mode="json")}
        )
    except Exception:
        # A disconnected observer can replay the committed event without a run.
        pass


def read_events(
    thread_id,
    run_id,
    research_id,
    turn_id,
    attempt_id,
    after=0,
    limit=50,
    journal_id=None,
):
    """Read a strictly owned, continuous page without dispatching any execution."""
    if not 0 <= after <= MAX_SAFE_INTEGER or not 1 <= limit <= 100:
        raise ValueError("Invalid page")
    store = _store()
    with store.connection() as db:
        identity, revision, _ = _identity(db, store, thread_id, run_id)
        if (identity["research_id"], identity["turn_id"], identity["attempt_id"]) != (
            research_id,
            turn_id,
            attempt_id,
        ):
            raise WorkflowContractError("workflow_event_identity_mismatch")
        result = {
            "version": 1,
            **identity,
            "status": "missing",
            "journal_id": None,
            "events": [],
            "next_sequence": 0,
            "last_sequence": 0,
            "has_more": False,
            "sealed": False,
            "gap": False,
            "reset": False,
            "unconfirmed_before_sequence": 0,
        }
        row = db.execute(
            "SELECT * FROM workflow_event_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            return result
        orphaned = not row["sealed"] and row["owner_id"] != INSTANCE_ID
        count, maximum = db.execute(
            "SELECT COUNT(*), COALESCE(MAX(sequence), 0) FROM workflow_node_events WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if count != maximum or maximum != row["last_sequence"]:
            raise WorkflowContractError("workflow_event_sequence_conflict")
        reset = (
            after > maximum
            or journal_id is not None
            and journal_id != row["journal_id"]
        )
        if reset:
            after = 0
        rows = db.execute(
            "SELECT * FROM workflow_node_events WHERE run_id=? AND sequence>? ORDER BY sequence LIMIT ?",
            (run_id, after, limit + 1),
        ).fetchall()
        events = []
        for index, item in enumerate(rows[:limit], start=after + 1):
            event = WorkflowNodeEvent.model_validate_json(item["payload"])
            _check_event(event, identity, revision)
            if (
                event.sequence != index
                or item["sequence"] != index
                or event.id != item["event_id"]
            ):
                raise WorkflowContractError("workflow_event_sequence_conflict")
            events.append(event.model_dump(mode="json"))
        return {
            **result,
            "status": "ready",
            "journal_id": row["journal_id"],
            "events": events,
            "last_sequence": maximum,
            "next_sequence": events[-1]["sequence"] if len(rows) > limit else maximum,
            "has_more": len(rows) > limit,
            "sealed": bool(row["sealed"]),
            "gap": bool(orphaned or reset),
            "reset": reset,
            "unconfirmed_before_sequence": maximum if orphaned else 0,
        }


async def events(request):
    """Expose parent observations separately from dynamic researcher events."""
    try:
        query = request.query_params
        payload = await run_in_threadpool(
            read_events,
            str(request.path_params["thread_id"]),
            str(request.path_params["run_id"]),
            query["research_id"],
            query["turn_id"],
            query["attempt_id"],
            int(query.get("after", "0")),
            int(query.get("limit", "50")),
            query.get("journal_id"),
        )
        status = 200
    except WorkflowContractError as exc:
        payload, status = {"reason": exc.reason}, 409
    except WorkflowStoreError as exc:
        payload, status = exc.payload(), exc.status
    except (KeyError, ValueError):
        payload, status = {"reason": "workflow_event_request_invalid"}, 400
    except Exception:
        payload, status = {"reason": "workflow_events_unavailable"}, 503
    return JSONResponse(
        payload, status_code=status, headers={"Cache-Control": "no-store"}
    )
