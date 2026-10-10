"""Local, durable replay of safe research events; never an execution queue.

Each append commits before the event is published. Native run/checkpoint state
remains authoritative for execution. Only the full graph's native API runs use
this journal; standalone graphs and evaluations need no storage configuration.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

INSTANCE_ID = str(uuid4())
_SCHEMA_LOCK = threading.Lock()


@dataclass(frozen=True)
class EventIdentity:
    """Bind replay to a server thread/run and one logical submission."""

    thread_id: str
    run_id: str
    research_id: str
    turn_id: str

    @property
    def key(self) -> tuple[str, str]:
        return self.thread_id, self.run_id

    def public(self) -> dict:
        return vars(self).copy()


def journal_path() -> Path | None:
    """Keep fixture storage opt-in when native file persistence is disabled."""
    configured = os.getenv("ATLAS_EVENT_DB")
    if configured:
        return Path(configured).resolve()
    if os.getenv("LANGGRAPH_DISABLE_FILE_PERSISTENCE", "false").lower() == "true":
        return None
    return Path(".langgraph_api/atlas-events.sqlite3").resolve()


def get_event_journal() -> EventJournal | None:
    path = journal_path()
    if path is None:
        return None
    days = int(os.getenv("ATLAS_EVENT_RETENTION_DAYS", "30"))
    if not 1 <= days <= 3650:
        raise ValueError("ATLAS_EVENT_RETENTION_DAYS must be between 1 and 3650")
    return EventJournal(path, retention_seconds=days * 86400)


class EventJournal:
    """SQLite transactions survive process termination without a final checkpoint."""

    def __init__(self, path: Path, *, retention_seconds: float = 30 * 86400):
        self.path = path
        self.retention_seconds = retention_seconds

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=1)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA foreign_keys=ON")
            # Changing journal mode on a new database can fail immediately with
            # SQLITE_BUSY, before SQLite's transaction busy timeout applies.
            # Serialize initialization across local research/tool threads.
            with _SCHEMA_LOCK:
                self._initialize(db)
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _initialize(db):
        if db.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
            db.execute("PRAGMA journal_mode=WAL")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version == 2:
            return
        if version not in (0, 1):
            raise ValueError("Unsupported event journal schema")
        with db:
            db.execute("BEGIN IMMEDIATE")
            # Another process may have migrated while we waited for its lock.
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version == 2:
                return
            if version not in (0, 1):
                raise ValueError("Unsupported event journal schema")
            db.execute("""
                CREATE TABLE IF NOT EXISTS event_runs (
                    thread_id TEXT NOT NULL, run_id TEXT NOT NULL,
                    research_id TEXT NOT NULL, turn_id TEXT NOT NULL,
                    journal_id TEXT NOT NULL, last_sequence INTEGER NOT NULL DEFAULT 0,
                    sealed INTEGER NOT NULL DEFAULT 0, gap INTEGER NOT NULL DEFAULT 0,
                    expired INTEGER NOT NULL DEFAULT 0, updated REAL NOT NULL,
                    owner_id TEXT NOT NULL DEFAULT '',
                    unconfirmed_before INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (thread_id, run_id)
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS research_events (
                    thread_id TEXT NOT NULL, run_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL, event_id TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY (thread_id, run_id, sequence),
                    UNIQUE (thread_id, run_id, event_id),
                    FOREIGN KEY (thread_id, run_id) REFERENCES event_runs ON DELETE CASCADE
                )
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(event_runs)")}
            if "owner_id" not in columns:
                db.execute(
                    "ALTER TABLE event_runs ADD COLUMN owner_id TEXT NOT NULL DEFAULT ''"
                )
                db.execute(
                    "ALTER TABLE event_runs ADD COLUMN unconfirmed_before INTEGER NOT NULL DEFAULT 0"
                )
            db.execute("PRAGMA user_version=2")

    def _prune(self, db, now: float):
        # Retain small tombstones for another retention interval, so clients can
        # distinguish expired history from a stream that has not started yet.
        cutoff = now - self.retention_seconds
        db.execute(
            "DELETE FROM research_events WHERE (thread_id, run_id) IN "
            "(SELECT thread_id, run_id FROM event_runs WHERE updated < ?)",
            (cutoff,),
        )
        db.execute("UPDATE event_runs SET expired=1 WHERE updated < ?", (cutoff,))
        db.execute(
            "DELETE FROM event_runs WHERE updated < ?",
            (now - 2 * self.retention_seconds,),
        )

    @staticmethod
    def _row(db, identity: EventIdentity):
        row = db.execute(
            "SELECT * FROM event_runs WHERE thread_id=? AND run_id=?", identity.key
        ).fetchone()
        if row and (row["research_id"], row["turn_id"]) != (
            identity.research_id,
            identity.turn_id,
        ):
            raise ValueError("Event journal identity mismatch")
        return row

    def begin(self, identity: EventIdentity) -> int:
        """Continue sequence numbers across native attempts of the same run."""
        now = time.time()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._prune(db, now)
            row = self._row(db, identity)
            if row:
                # A new capture cannot keep unfinished tasks from an earlier
                # attempt looking active, even if both used the same process.
                unconfirmed = row["last_sequence"]
                db.execute(
                    "UPDATE event_runs SET sealed=0, gap=MAX(gap, expired, ?), "
                    "unconfirmed_before=MAX(unconfirmed_before, ?), owner_id=?, "
                    "expired=0, updated=? WHERE thread_id=? AND run_id=?",
                    (
                        int(not row["sealed"]),
                        unconfirmed,
                        INSTANCE_ID,
                        now,
                        *identity.key,
                    ),
                )
                return row["last_sequence"]
            db.execute(
                "INSERT INTO event_runs "
                "(thread_id, run_id, research_id, turn_id, journal_id, updated, owner_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    *identity.key,
                    identity.research_id,
                    identity.turn_id,
                    str(uuid4()),
                    now,
                    INSTANCE_ID,
                ),
            )
            return 0

    def append(self, identity: EventIdentity, event: dict):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, identity)
            if row is None or event["sequence"] <= row["last_sequence"]:
                raise ValueError("Event journal sequence conflict")
            if (event["research_id"], event["turn_id"]) != (
                identity.research_id,
                identity.turn_id,
            ):
                raise ValueError("Event identity mismatch")
            db.execute(
                "INSERT INTO research_events VALUES (?, ?, ?, ?, ?)",
                (
                    *identity.key,
                    event["sequence"],
                    event["id"],
                    json.dumps(event, ensure_ascii=False),
                ),
            )
            db.execute(
                "UPDATE event_runs SET last_sequence=?, gap=MAX(gap, ?), updated=? "
                "WHERE thread_id=? AND run_id=?",
                (
                    event["sequence"],
                    int(event["sequence"] != row["last_sequence"] + 1),
                    time.time(),
                    *identity.key,
                ),
            )

    def finish(self, identity: EventIdentity, sequence: int, *, gap: bool):
        with self.connection() as db:
            db.execute(
                "UPDATE event_runs SET sealed=1, gap=MAX(gap, ?, last_sequence < ?), "
                "last_sequence=MAX(last_sequence, ?), updated=? WHERE thread_id=? AND run_id=?",
                (int(gap), sequence, sequence, time.time(), *identity.key),
            )

    def read(
        self,
        identity: EventIdentity,
        after: int = 0,
        limit: int = 50,
        journal_id: str | None = None,
    ) -> dict:
        if after < 0 or not 1 <= limit <= 100:
            raise ValueError("Invalid event page")
        result = {
            "version": 1,
            **identity.public(),
            "status": "missing",
            "journal_id": None,
            "events": [],
            "next_sequence": 0,
            "last_sequence": 0,
            "has_more": False,
            "sealed": False,
            "gap": True,
            "reset": False,
            "unconfirmed_before_sequence": 0,
        }
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._prune(db, time.time())
            row = self._row(db, identity)
            if row is None:
                return result
            orphaned = not row["sealed"] and row["owner_id"] != INSTANCE_ID
            result.update(
                status="expired" if row["expired"] else "ready",
                journal_id=row["journal_id"],
                last_sequence=row["last_sequence"],
                sealed=bool(row["sealed"]),
                gap=bool(row["gap"] or row["expired"] or orphaned),
                unconfirmed_before_sequence=max(
                    row["unconfirmed_before"], row["last_sequence"] if orphaned else 0
                ),
            )
            if row["expired"]:
                return result
            reset = after > row["last_sequence"] or (
                journal_id is not None and journal_id != row["journal_id"]
            )
            if reset:
                after = 0
            rows = db.execute(
                "SELECT payload FROM research_events WHERE thread_id=? AND run_id=? "
                "AND sequence>? ORDER BY sequence LIMIT ?",
                (*identity.key, after, limit + 1),
            ).fetchall()
            events = [json.loads(row["payload"]) for row in rows[:limit]]
            more = len(rows) > limit
            # If a final write failed, advance past the explicitly recorded gap;
            # otherwise an empty final page would loop forever.
            next_sequence = events[-1]["sequence"] if more else row["last_sequence"]
            result.update(
                events=events,
                next_sequence=next_sequence,
                has_more=more,
                reset=reset,
                gap=result["gap"] or reset,
            )
            return result
