"""Durable submission identities and execution attempts for the Atlas local API.

The intent, including its run UUID, commits BEFORE native run creation. A node
must claim the recorded attempt before any model/tool call. Losing a response
can therefore never turn the same request into a second native run identity.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from deep_research.atlas_runtime import flush_native, submissions_enabled
from deep_research.event_journal import INSTANCE_ID

_SCHEMA_LOCK = threading.Lock()
SAFE_NODES = {
    "clarify_with_user": "clarify",
    "write_research_brief": "brief",
    "final_report_generation": "writing",
}
TERMINAL = {"awaiting_input", "succeeded", "failed", "partial"}


class SubmissionConflict(ValueError):
    """A key or predecessor does not describe the already accepted operation."""


def digest(payload) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def state_digest(state) -> str:
    """Compare the inputs used by recoverable nodes without storing credentials."""
    messages = []
    for message in state.get("messages", []):
        if isinstance(message, dict):
            messages.append(
                {key: message.get(key) for key in ("id", "type", "content", "name")}
            )
        else:
            messages.append(
                {
                    key: getattr(message, key, None)
                    for key in ("id", "type", "content", "name")
                }
            )
    return digest(
        {
            **{
                key: state.get(key)
                for key in (
                    "active_research_id",
                    "active_turn_id",
                    "research_status",
                    "research_phase",
                    "research_brief",
                    "notes",
                    "sources",
                    "research_errors",
                    "supervisor_status",
                    "effective_config",
                    "final_report",
                    "report_research_id",
                )
            },
            "messages": messages,
        }
    )


def get_submission_journal():
    if not submissions_enabled():
        return None
    return SubmissionJournal(
        Path(
            os.getenv("ATLAS_SUBMISSION_DB")
            or ".langgraph_api/atlas-submissions.sqlite3"
        ).resolve()
    )


class SubmissionJournal:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA foreign_keys=ON")
            with _SCHEMA_LOCK:
                if db.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
                    db.execute("PRAGMA journal_mode=WAL")
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, 1, 2):
                    raise ValueError("Unsupported submission journal")
                if version == 0:
                    db.executescript("""
                        CREATE TABLE IF NOT EXISTS submissions (
                            thread_id TEXT NOT NULL, turn_id TEXT NOT NULL,
                            research_id TEXT NOT NULL, payload TEXT NOT NULL,
                            payload_hash TEXT NOT NULL, created REAL NOT NULL,
                            PRIMARY KEY (thread_id, turn_id)
                        );
                        CREATE TABLE IF NOT EXISTS attempts (
                            thread_id TEXT NOT NULL, turn_id TEXT NOT NULL,
                            attempt_id TEXT NOT NULL, run_id TEXT NOT NULL UNIQUE,
                            kind TEXT NOT NULL, checkpoint_id TEXT, checkpoint_node TEXT,
                            parent_run_id TEXT, owner_id TEXT, last_node TEXT,
                            state_hash TEXT, dispatched INTEGER NOT NULL DEFAULT 0,
                            rejected INTEGER NOT NULL DEFAULT 0,
                            completed_checkpoint TEXT,
                            created REAL NOT NULL,
                            PRIMARY KEY (thread_id, turn_id, attempt_id),
                            FOREIGN KEY (thread_id, turn_id) REFERENCES submissions(thread_id, turn_id)
                        );
                        PRAGMA user_version=2;
                    """)
                elif version == 1:
                    db.execute(
                        "ALTER TABLE attempts ADD COLUMN completed_checkpoint TEXT"
                    )
                    db.execute("PRAGMA user_version=2")
                    db.commit()
            with db:
                db.execute("BEGIN IMMEDIATE")
                yield db
        finally:
            db.close()

    def get(self, thread_id, turn_id):
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM submissions WHERE thread_id=? AND turn_id=?",
                (thread_id, turn_id),
            ).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["payload"] = json.loads(result["payload"])
            result["attempts"] = [
                dict(item)
                for item in db.execute(
                    "SELECT * FROM attempts WHERE thread_id=? AND turn_id=? ORDER BY rowid",
                    (thread_id, turn_id),
                )
            ]
            return result

    def latest(self, thread_id):
        with self.connection() as db:
            row = db.execute(
                "SELECT turn_id FROM submissions WHERE thread_id=? ORDER BY rowid DESC LIMIT 1",
                (thread_id,),
            ).fetchone()
        return self.get(thread_id, row[0]) if row else None

    def reserve(self, thread_id, turn_id, payload):
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        with self.connection() as db:
            prior = db.execute(
                "SELECT payload_hash FROM submissions WHERE thread_id=? AND turn_id=?",
                (thread_id, turn_id),
            ).fetchone()
            if prior:
                if prior[0] != digest(payload):
                    raise SubmissionConflict("submission_payload_conflict")
            else:
                db.execute(
                    "INSERT INTO submissions VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        thread_id,
                        turn_id,
                        payload["research_id"],
                        encoded,
                        digest(payload),
                        time.time(),
                    ),
                )
                db.execute(
                    "INSERT INTO attempts (thread_id, turn_id, attempt_id, run_id, kind, created) VALUES (?, ?, ?, ?, 'submit', ?)",
                    (thread_id, turn_id, turn_id, str(uuid4()), time.time()),
                )
        return self.get(thread_id, turn_id)

    def reserve_recovery(self, record, attempt_id, parent_run_id, checkpoint_id, node):
        with self.connection() as db:
            prior = db.execute(
                "SELECT * FROM attempts WHERE thread_id=? AND turn_id=? AND attempt_id=?",
                (record["thread_id"], record["turn_id"], attempt_id),
            ).fetchone()
            if prior:
                if (
                    prior["kind"] != "resume"
                    or prior["parent_run_id"] != parent_run_id
                    or prior["checkpoint_id"] != checkpoint_id
                ):
                    raise SubmissionConflict("recovery_payload_conflict")
            else:
                latest = db.execute(
                    "SELECT run_id FROM attempts WHERE thread_id=? AND turn_id=? ORDER BY rowid DESC LIMIT 1",
                    (record["thread_id"], record["turn_id"]),
                ).fetchone()
                if latest[0] != parent_run_id:
                    raise SubmissionConflict("recovery_attempt_conflict")
                db.execute(
                    "INSERT INTO attempts (thread_id, turn_id, attempt_id, run_id, kind, checkpoint_id, checkpoint_node, parent_run_id, created) VALUES (?, ?, ?, ?, 'resume', ?, ?, ?, ?)",
                    (
                        record["thread_id"],
                        record["turn_id"],
                        attempt_id,
                        str(uuid4()),
                        checkpoint_id,
                        node,
                        parent_run_id,
                        time.time(),
                    ),
                )
        return self.get(record["thread_id"], record["turn_id"])

    def mark(self, run_id, *, dispatched=False, rejected=False):
        with self.connection() as db:
            db.execute(
                "UPDATE attempts SET dispatched=MAX(dispatched, ?), rejected=MAX(rejected, ?) WHERE run_id=?",
                (int(dispatched), int(rejected), run_id),
            )

    def confirm_completed(self, run_id, checkpoint_id):
        with self.connection() as db:
            db.execute(
                "UPDATE attempts SET completed_checkpoint=? WHERE run_id=?",
                (checkpoint_id, run_id),
            )

    def enter_node(self, run_id, thread_id, node, state):
        with self.connection() as db:
            row = db.execute(
                "SELECT a.*, s.research_id FROM attempts a JOIN submissions s USING (thread_id, turn_id) WHERE a.run_id=? AND a.thread_id=?",
                (run_id, thread_id),
            ).fetchone()
            if (
                row is None
                or row["rejected"]
                or row["owner_id"] not in (None, INSTANCE_ID)
            ):
                raise SubmissionConflict("execution_requires_recovery")
            if row["kind"] == "resume" and row["owner_id"] is None:
                if (
                    node != row["checkpoint_node"]
                    or state.get("active_research_id") != row["research_id"]
                    or state.get("active_turn_id") != row["turn_id"]
                ):
                    raise SubmissionConflict("recovery_checkpoint_changed")
            db.execute(
                "UPDATE attempts SET owner_id=?, last_node=?, state_hash=?, dispatched=1 WHERE run_id=?",
                (INSTANCE_ID, node, state_digest(state), run_id),
            )


def guard_execution(state, node):
    """Fence only Atlas managed runs; independent graphs/evaluators are unchanged."""
    from langgraph.config import get_config

    try:
        config = get_config()
    except RuntimeError:
        return
    if config.get("metadata", {}).get("atlas_submission_version") != 1:
        return
    journal = get_submission_journal()
    if journal is None:
        raise SubmissionConflict("execution_journal_unavailable")
    configurable = config["configurable"]
    journal.enter_node(
        str(configurable["run_id"]), str(configurable["thread_id"]), node, state
    )
    # The claim commits first; a crash before this barrier cannot allow a second
    # process to execute the same attempt. No provider calls occur before both.
    flush_native(checkpoints=True)
