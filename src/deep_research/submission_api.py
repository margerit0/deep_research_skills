"""Idempotent Atlas acceptance and explicit, checked execution recovery."""

from __future__ import annotations

import logging
from json import JSONDecodeError
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from deep_research.atlas_runtime import flush_native, native_modules
from deep_research.event_journal import INSTANCE_ID
from deep_research.submission_journal import (
    SAFE_NODES,
    TERMINAL,
    SubmissionConflict,
    digest,
    get_submission_journal,
    state_digest,
)
from deep_research.workflow_contract import is_research_note

logger = logging.getLogger(__name__)


class Submission(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    research_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=50000)
    expected_turn_id: str | None = Field(max_length=128)


class Recovery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    research_id: str = Field(min_length=1, max_length=128)
    parent_run_id: str
    checkpoint_id: str

    @field_validator("parent_run_id", "checkpoint_id")
    @classmethod
    def valid_uuid(cls, value):
        return str(UUID(value))


def response(payload, status=200):
    return JSONResponse(
        payload, status_code=status, headers={"Cache-Control": "no-store"}
    )


async def create_native(conn, thread_id, payload, headers, run_id):
    return await native_modules()[4](
        conn, thread_id, payload, headers, run_id=UUID(run_id)
    )


def native_run(conn, thread_id, run_id):
    return next(
        (
            run
            for run in conn.store["runs"]
            if str(run["thread_id"]) == thread_id and str(run["run_id"]) == run_id
        ),
        None,
    )


async def read_snapshot(conn, thread_id, checkpoint_id=None):
    configurable = {"thread_id": thread_id}
    if checkpoint_id:
        configurable["checkpoint_id"] = checkpoint_id
    return await native_modules()[3].State.get(conn, {"configurable": configurable})


def matching_state(record, snapshot):
    values = snapshot.values
    return (
        values.get("active_research_id") == record["research_id"]
        and values.get("active_turn_id") == record["turn_id"]
    )


def recovery_boundary(record, snapshot):
    attempt = record["attempts"][-1]
    denied = {"allowed": False, "reason": "checkpoint_unverified"}
    if (
        not matching_state(record, snapshot)
        or len(snapshot.next) != 1
        or not snapshot.config
    ):
        return denied
    node = snapshot.next[0]
    values = snapshot.values
    if node not in SAFE_NODES:
        return {"allowed": False, "reason": "research_node_not_resumable"}
    if (
        values.get("research_status") != "running"
        or values.get("research_phase") != SAFE_NODES[node]
    ):
        return denied
    if str((snapshot.metadata or {}).get("run_id", "")) != attempt["run_id"]:
        return denied
    # A recorded node entry proves the complete input used before interruption.
    # Reject rolled-back, partially persisted, or externally edited checkpoints.
    if attempt["last_node"] != node or attempt["state_hash"] != state_digest(values):
        return denied
    if effective := values.get("effective_config"):
        from deep_research.model_config import public_model_config

        if effective.get("models") != public_model_config()["models"]:
            return {"allowed": False, "reason": "configuration_changed"}
    if node == "final_report_generation" and not any(
        is_research_note(note) for note in values.get("notes", [])
    ):
        return denied
    checkpoint_id = snapshot.config.get("configurable", {}).get("checkpoint_id")
    if not checkpoint_id:
        return denied
    return {
        "allowed": True,
        "checkpoint_id": str(checkpoint_id),
        "node": node,
        "reason": "model_call_may_repeat",
    }


async def receipt(conn, record):
    thread_id = record["thread_id"]
    attempt = record["attempts"][-1]
    run = native_run(conn, thread_id, attempt["run_id"])
    payload = {
        "version": 1,
        "thread_id": thread_id,
        "research_id": record["research_id"],
        "turn_id": record["turn_id"],
        "attempt_id": attempt["attempt_id"],
        "run_id": attempt["run_id"],
        "event_run_id": next(
            item["run_id"]
            for item in reversed(record["attempts"])
            if item["checkpoint_node"] != "final_report_generation"
        ),
        "attempts": [
            {key: item[key] for key in ("attempt_id", "run_id", "kind")}
            for item in record["attempts"]
        ],
        "status": "accepted",
        "reason": "accepted",
        "retry_allowed": False,
        "recovery": {"allowed": False, "reason": "execution_active"},
        "run": None
        if run is None
        else {
            "thread_id": thread_id,
            "run_id": str(run["run_id"]),
            "status": run["status"],
            "metadata": {
                "atlas_research_id": record["research_id"],
                "atlas_turn_id": record["turn_id"],
            },
        },
    }
    thread = next(
        (item for item in conn.store["threads"] if str(item["thread_id"]) == thread_id),
        None,
    )
    if thread is None:
        return {**payload, "status": "blocked", "reason": "thread_missing"}
    if attempt["rejected"]:
        return {**payload, "status": "rejected", "reason": "thread_conflict"}
    if run is None:
        if attempt["owner_id"] is None:
            return {
                **payload,
                "status": "retryable",
                "reason": "dispatch_unconfirmed",
                "retry_allowed": True,
            }
        return {**payload, "status": "blocked", "reason": "run_missing"}
    if (
        run["metadata"].get("atlas_turn_id") != record["turn_id"]
        or run["metadata"].get("atlas_research_id") != record["research_id"]
    ):
        return {**payload, "status": "blocked", "reason": "run_identity_mismatch"}
    try:
        snapshot = await read_snapshot(conn, thread_id, attempt["completed_checkpoint"])
    except Exception:
        return {**payload, "status": "blocked", "reason": "checkpoint_unavailable"}
    complete = (
        matching_state(record, snapshot)
        and not snapshot.next
        and snapshot.values.get("research_status") in TERMINAL
        and str((snapshot.metadata or {}).get("run_id", "")) == attempt["run_id"]
    )
    if complete:
        checkpoint_id = str(snapshot.config["configurable"]["checkpoint_id"])
        if not attempt["completed_checkpoint"]:
            # Confirmation must outlive both a crash and subsequent turns. This
            # persists evidence only: it does not create/resume or mark a run.
            flush_native(checkpoints=True)
            get_submission_journal().confirm_completed(attempt["run_id"], checkpoint_id)
        return {
            **payload,
            "status": "completed",
            "checkpoint_id": checkpoint_id,
            "reason": "checkpoint_completed",
            "recovery": {"allowed": False, "reason": "already_completed"},
        }
    if attempt["completed_checkpoint"]:
        return {**payload, "status": "blocked", "reason": "checkpoint_unavailable"}
    if attempt["owner_id"] not in (None, INSTANCE_ID) or run["status"] not in (
        "pending",
        "running",
    ):
        if attempt["owner_id"] is None:
            return {
                **payload,
                "status": "retryable",
                "reason": "execution_not_started",
                "retry_allowed": True,
            }
        boundary = (
            recovery_boundary(record, snapshot)
            if attempt["owner_id"] != INSTANCE_ID
            else {"allowed": False, "reason": "restart_required"}
        )
        return {
            **payload,
            "status": "interrupted",
            "reason": boundary["reason"],
            "recovery": boundary,
        }
    return payload


async def dispatch(conn, journal, record, headers):
    attempt = record["attempts"][-1]
    if attempt["owner_id"] is not None or attempt["rejected"]:
        return
    run = native_run(conn, record["thread_id"], attempt["run_id"])
    if run is not None and (
        run["metadata"].get("atlas_turn_id") != record["turn_id"]
        or run["metadata"].get("atlas_research_id") != record["research_id"]
        or run["metadata"].get("atlas_attempt_id") != attempt["attempt_id"]
    ):
        raise SubmissionConflict("run_identity_mismatch")
    if run is not None and run["status"] in ("pending", "running"):
        return
    if attempt["kind"] == "resume":
        snapshot = await read_snapshot(conn, record["thread_id"])
        if (
            not matching_state(record, snapshot)
            or list(snapshot.next) != [attempt["checkpoint_node"]]
            or not snapshot.config
            or str(snapshot.config["configurable"].get("checkpoint_id"))
            != attempt["checkpoint_id"]
        ):
            raise SubmissionConflict("recovery_checkpoint_changed")
        # This is also used after a crash between recovery reservation and
        # dispatch. The same attempt key must finish the original acceptance.
        parent = next(
            item
            for item in record["attempts"]
            if item["run_id"] == attempt["parent_run_id"]
        )
        if parent["owner_id"] in (None, INSTANCE_ID):
            raise SubmissionConflict("recovery_not_available")
        await native_modules()[2].set_status(
            conn, UUID(attempt["parent_run_id"]), "interrupted"
        )
    elif run is None:
        snapshot = await read_snapshot(conn, record["thread_id"])
        if (
            snapshot.values.get("active_turn_id")
            != record["payload"]["expected_turn_id"]
        ):
            raise SubmissionConflict("thread_changed")
    other = [
        item
        for item in conn.store["runs"]
        if str(item["thread_id"]) == record["thread_id"]
        and str(item["run_id"]) != attempt["run_id"]
        and item["status"] in ("pending", "running")
    ]
    if other:
        raise SubmissionConflict("thread_conflict")
    if run is None:
        payload = {
            "assistant_id": "research_agent_full",
            "input": None
            if attempt["kind"] == "resume"
            else {
                "research_id": record["research_id"],
                "turn_id": record["turn_id"],
                "messages": [
                    {
                        "type": "human",
                        "id": record["turn_id"],
                        "content": record["payload"]["text"],
                    }
                ],
            },
            "metadata": {
                "atlas_research_id": record["research_id"],
                "atlas_turn_id": record["turn_id"],
                "atlas_attempt_id": attempt["attempt_id"],
                "atlas_submission_version": 1,
            },
            "multitask_strategy": "reject",
            "if_not_exists": "reject",
            "durability": "sync",
            "stream_mode": ["custom"],
            "stream_resumable": True,
        }
        if attempt["checkpoint_id"]:
            payload["checkpoint_id"] = attempt["checkpoint_id"]
        await create_native(
            conn, record["thread_id"], payload, headers, attempt["run_id"]
        )
    else:
        # No node ever claimed this identity, so no external call can be repeated.
        await native_modules()[2].set_status(conn, UUID(attempt["run_id"]), "pending")
    flush_native()
    journal.mark(attempt["run_id"], dispatched=True)


async def submit(request):
    return await handle(request, "submit")


async def get_receipt(request):
    return await handle(request, "read")


async def recover(request):
    return await handle(request, "recover")


async def handle(request, operation):
    try:
        journal = get_submission_journal()
        if journal is None:
            return response({"reason": "submission_contract_unavailable"}, 503)
        connect, lock, _, _, _ = native_modules()
        thread_id, turn_id = (
            str(request.path_params["thread_id"]),
            str(request.path_params["turn_id"]),
        )
        body = None
        if operation == "submit":
            body = Submission.model_validate(await request.json()).model_dump()
            if not body["text"].strip():
                return response({"reason": "invalid_submission"}, 400)
        elif operation == "recover":
            body = Recovery.model_validate(await request.json()).model_dump()
        async with connect() as conn, lock:
            record = journal.get(thread_id, turn_id)
            if operation == "read":
                if record is None:
                    # A missing ledger key is not a license to retry a legacy run.
                    exists = any(
                        str(item["thread_id"]) == thread_id
                        for item in conn.store["threads"]
                    )
                    return response(
                        {
                            "reason": "submission_unknown"
                            if exists
                            else "thread_missing"
                        },
                        404,
                    )
                return response(await receipt(conn, record))
            if record is not None and body["research_id"] != record["research_id"]:
                raise SubmissionConflict("submission_payload_conflict")
            if operation == "submit":
                if record is not None and digest(body) != record["payload_hash"]:
                    raise SubmissionConflict("submission_payload_conflict")
                if record is None:
                    if not any(
                        str(item["thread_id"]) == thread_id
                        for item in conn.store["threads"]
                    ):
                        return response({"reason": "thread_missing"}, 404)
                    latest = journal.latest(thread_id)
                    if latest:
                        prior = await receipt(conn, latest)
                        if prior["status"] != "completed":
                            raise SubmissionConflict("thread_conflict")
                        if prior["run"] and prior["run"]["status"] in (
                            "pending",
                            "running",
                        ):
                            # A complete, owned checkpoint can outlive the native
                            # worker's final status write. Do not strand the thread.
                            await native_modules()[2].set_status(
                                conn, UUID(prior["run_id"]), "success"
                            )
                    if any(
                        str(item["thread_id"]) == thread_id
                        and item["status"] in ("pending", "running")
                        for item in conn.store["runs"]
                    ):
                        raise SubmissionConflict("thread_conflict")
                    snapshot = await read_snapshot(conn, thread_id)
                    if body["expected_turn_id"] != snapshot.values.get(
                        "active_turn_id"
                    ):
                        raise SubmissionConflict("thread_changed")
                    if (
                        body["research_id"] == snapshot.values.get("active_research_id")
                        and snapshot.values.get("research_status") != "awaiting_input"
                    ):
                        raise SubmissionConflict("research_already_completed")
                    # The native thread must survive even if we exit after intent
                    # commit but before native run creation has completed.
                    flush_native()
                    record = journal.reserve(thread_id, turn_id, body)
                # Reposting the original turn always reconciles the latest attempt;
                # it never restarts the initial input after a recovery was accepted.
                await dispatch(conn, journal, record, request.headers)
            else:
                if record is None:
                    return response({"reason": "submission_unknown"}, 404)
                attempt_id = str(request.path_params["attempt_id"])
                prior = next(
                    (
                        item
                        for item in record["attempts"]
                        if item["attempt_id"] == attempt_id
                    ),
                    None,
                )
                if prior:
                    if (
                        prior["kind"] != "resume"
                        or prior["parent_run_id"] != body["parent_run_id"]
                        or prior["checkpoint_id"] != body["checkpoint_id"]
                    ):
                        raise SubmissionConflict("recovery_payload_conflict")
                    if prior["run_id"] == record["attempts"][-1]["run_id"]:
                        await dispatch(conn, journal, record, request.headers)
                    return response(await receipt(conn, record))
                current = await receipt(conn, record)
                boundary = current["recovery"]
                if current["status"] != "interrupted" or not boundary["allowed"]:
                    raise SubmissionConflict("recovery_not_available")
                if (
                    current["run_id"] != body["parent_run_id"]
                    or boundary["checkpoint_id"] != body["checkpoint_id"]
                ):
                    raise SubmissionConflict("recovery_checkpoint_changed")
                record = journal.reserve_recovery(
                    record,
                    attempt_id,
                    body["parent_run_id"],
                    body["checkpoint_id"],
                    boundary["node"],
                )
                # Only a verified recovery request retires an orphaned running run.
                await native_modules()[2].set_status(
                    conn, UUID(body["parent_run_id"]), "interrupted"
                )
                flush_native()
                await dispatch(conn, journal, record, request.headers)
            return response(await receipt(conn, journal.get(thread_id, turn_id)))
    except SubmissionConflict as exc:
        return response({"reason": str(exc)}, 409)
    except (ValidationError, JSONDecodeError):
        return response({"reason": "invalid_submission"}, 400)
    except HTTPException as exc:
        if (
            exc.status_code == 409
            and record
            and native_run(conn, thread_id, record["attempts"][-1]["run_id"]) is None
        ):
            journal.mark(record["attempts"][-1]["run_id"], rejected=True)
        return response(
            {
                "reason": "thread_conflict"
                if exc.status_code == 409
                else "native_request_rejected"
            },
            exc.status_code,
        )
    except Exception as exc:
        # Storage and native diagnostics belong in backend logs, never HTTP bodies.
        logger.warning("Atlas submission unavailable (%s)", type(exc).__name__)
        return response({"reason": "submission_temporarily_unavailable"}, 503)
