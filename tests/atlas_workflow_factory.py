"""M0-only revision store and Command routing adapter, not a public workflow API."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

GRAPH_ID = "research_workflow"
COMPILER = "m0-command-adapter-v1"
CORE = (
    "prepare_research",
    "clarify_with_user",
    "write_research_brief",
    "supervisor_subgraph",
    "final_report_generation",
)
EXTENDED = (*CORE[:3], "optimize_plan", CORE[3], "organize_notes", CORE[4])
NORMAL_DESTINATIONS = dict(zip(CORE, (*CORE[1:], END)))


class RevisionError(ValueError):
    pass


@dataclass(frozen=True)
class Revision:
    revision_id: str
    nodes: tuple[str, ...]
    compiler: str = COMPILER
    state_schema: int = 1

    @property
    def content_hash(self):
        semantic = asdict(self)
        semantic.pop("revision_id")
        return hashlib.sha256(
            json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def validate(self):
        if self.compiler != COMPILER or self.state_schema != 1:
            raise RevisionError("revision_incompatible")
        # Deliberately narrow M0 paths. M1 owns the general definition contract.
        allowed = (CORE, EXTENDED, tuple(n for n in CORE if n != "clarify_with_user"))
        if (
            not self.revision_id
            or len(self.revision_id) > 128
            or self.nodes not in allowed
        ):
            raise RevisionError("revision_invalid")
        return self


class RevisionStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS revisions (
                    revision_id TEXT PRIMARY KEY, definition TEXT NOT NULL,
                    content_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS bindings (
                    thread_id TEXT PRIMARY KEY, revision_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL, name TEXT NOT NULL,
                    thread_id TEXT NOT NULL, run_id TEXT NOT NULL,
                    revision_id TEXT NOT NULL, detail TEXT NOT NULL
                );
                """
            )

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def publish(self, revision: Revision):
        revision.validate()
        definition = json.dumps(asdict(revision), sort_keys=True)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT definition FROM revisions WHERE revision_id=?",
                (revision.revision_id,),
            ).fetchone()
            if old and old["definition"] != definition:
                raise RevisionError("revision_immutable")
            db.execute(
                "INSERT OR IGNORE INTO revisions VALUES (?, ?, ?)",
                (revision.revision_id, definition, revision.content_hash),
            )
        return revision

    @staticmethod
    def _load(db, revision_id):
        row = db.execute(
            "SELECT * FROM revisions WHERE revision_id=?", (revision_id,)
        ).fetchone()
        if row is None:
            raise RevisionError("revision_missing")
        try:
            data = json.loads(row["definition"])
            data["nodes"] = tuple(data["nodes"])
            revision = Revision(**data).validate()
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise RevisionError("revision_invalid") from exc
        if revision.revision_id != revision_id:
            raise RevisionError("revision_identity_mismatch")
        if revision.content_hash != row["content_hash"]:
            raise RevisionError("revision_hash_mismatch")
        return revision

    def bind(self, thread_id: str, revision_id: str):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            revision = self._load(db, revision_id)
            old = db.execute(
                "SELECT * FROM bindings WHERE thread_id=?", (thread_id,)
            ).fetchone()
            if old and (
                old["revision_id"] != revision_id
                or old["content_hash"] != revision.content_hash
            ):
                raise RevisionError("thread_revision_conflict")
            db.execute(
                "INSERT OR IGNORE INTO bindings VALUES (?, ?, ?)",
                (thread_id, revision_id, revision.content_hash),
            )
        return revision

    def resolve(self, thread_id: str, requested: str | None = None):
        with self.connect() as db:
            binding = db.execute(
                "SELECT * FROM bindings WHERE thread_id=?", (thread_id,)
            ).fetchone()
            if binding is None:
                raise RevisionError("thread_revision_missing")
            if requested is not None and requested != binding["revision_id"]:
                raise RevisionError("thread_revision_conflict")
            revision = self._load(db, binding["revision_id"])
            if binding["content_hash"] != revision.content_hash:
                raise RevisionError("binding_hash_mismatch")
            return revision

    def record(self, kind, name, config, revision_id="", **detail):
        configurable = config.get("configurable", {})
        with self.connect() as db:
            db.execute(
                "INSERT INTO audit(kind,name,thread_id,run_id,revision_id,detail) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    kind,
                    name,
                    str(configurable.get("thread_id", "")),
                    str(configurable.get("run_id", "")),
                    revision_id,
                    json.dumps(detail, sort_keys=True, ensure_ascii=False),
                ),
            )

    def audit(self):
        with self.connect() as db:
            return [
                {**dict(row), "detail": json.loads(row["detail"])}
                for row in db.execute("SELECT * FROM audit ORDER BY sequence")
            ]


def routed(result, normal_destination, successor):
    """Replace the legacy normal goto; retain system END and all reducer values."""
    if isinstance(result, Command):
        if (
            result.graph
            or result.resume
            or result.goto not in (normal_destination, END)
        ):
            raise RevisionError("unsupported_business_route")
        if result.update is not None and not isinstance(result.update, dict):
            raise RevisionError("unsupported_business_update")
        destination = END if result.goto == END else successor
        return Command(update=result.update, goto=destination)
    if not isinstance(result, dict):
        raise RevisionError("unsupported_business_result")
    return Command(update=result, goto=successor)


def compile_revision(
    revision, handlers, state_schema, input_schema=None, on_entry=None
):
    revision.validate()
    builder = StateGraph(state_schema, input_schema=input_schema)

    def adapt(name, successor):
        handler = handlers[name]

        async def execute(state, config: RunnableConfig):
            if state.get("workflow_revision_id") not in (None, revision.revision_id):
                raise RevisionError("checkpoint_revision_conflict")
            if state.get("workflow_content_hash") not in (None, revision.content_hash):
                raise RevisionError("checkpoint_revision_conflict")
            if on_entry:
                await on_entry(name, state, config, revision)
            result = (
                await handler(state)
                if inspect.iscoroutinefunction(handler)
                else await asyncio.to_thread(handler, state)
            )
            command = routed(result, NORMAL_DESTINATIONS.get(name), successor)
            update = {
                **(command.update or {}),
                "workflow_revision_id": revision.revision_id,
                "workflow_content_hash": revision.content_hash,
            }
            if name == "prepare_research" and command.goto == "write_research_brief":
                update["research_phase"] = "brief"
            return Command(update=update, goto=command.goto)

        return execute

    for index, name in enumerate(revision.nodes):
        successor = (
            revision.nodes[index + 1] if index + 1 < len(revision.nodes) else END
        )
        builder.add_node(
            name, adapt(name, successor), destinations=tuple({successor, END})
        )
    # Only START uses a static edge. Normal and terminal results both route once.
    builder.add_edge(START, revision.nodes[0])
    return builder.compile()
