"""Safe researcher progress shared by the native custom stream and checkpoint.

The recorder belongs to one invocation of the full graph's research node.
Context variables carry it into parallel tasks and LangGraph's sync workers;
they are never serialized into model prompts or graph configuration.
"""

import os
import logging
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Literal, NotRequired, TypedDict
from uuid import NAMESPACE_URL, uuid4, uuid5

from langgraph.config import get_config, get_stream_writer

from deep_research.event_journal import EventIdentity, EventJournal, get_event_journal
from deep_research.workflow_contract import ResearchSource, merge_sources


EventKind = Literal[
    "delegated",
    "model_started",
    "model_finished",
    "model_failed",
    "tool_started",
    "tool_finished",
    "tool_failed",
    "compression_started",
    "compression_finished",
    "compression_failed",
    "completed",
    "failed",
]
PUBLIC_TOOLS = {"tavily_search", "load_skill", "think_tool"}
logger = logging.getLogger(__name__)


class ResearchEvent(TypedDict):
    """Versioned, bounded progress; no model reasoning or raw provider payloads."""

    version: Literal[1]
    id: str
    research_id: str
    turn_id: str
    sequence: int
    at: str
    task_id: str
    round: int
    kind: EventKind
    elapsed_ms: int
    topic: NotRequired[str]
    tool: NotRequired[str]
    query: NotRequired[str]
    sources: NotRequired[list[ResearchSource]]
    source_count: NotRequired[int]
    output: NotRequired[str]


@dataclass
class _Task:
    id: str
    round: int
    started: float = field(default_factory=time.monotonic)


@dataclass
class EventRecorder:
    """Keep an ordered transcript even when individual researchers fail."""

    research_id: str
    turn_id: str
    writer: Callable
    events: list[ResearchEvent] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    journal: EventJournal | None = None
    identity: EventIdentity | None = None
    sequence: int = 0
    journal_failed: bool = False
    capture_id: str = field(default_factory=lambda: str(uuid4()))
    secrets: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            value
            for name, value in os.environ.items()
            if value
            and name.upper().endswith(("_KEY", "_TOKEN", "_BASE_URL", "_PROXY"))
            and value != "*"
        )
    )

    def public_text(self, value: str, limit: int) -> str:
        for secret in self.secrets:
            value = value.replace(secret, "[redacted]")
        return value if len(value) <= limit else value[:limit] + "…（已截断）"

    def record(
        self,
        task: _Task,
        kind: EventKind,
        *,
        topic: str | None = None,
        tool: str | None = None,
        query: str | None = None,
        sources: list[ResearchSource] | None = None,
        output: str | None = None,
    ) -> None:
        # Serialize append + publish so parallel workers share a stable order.
        with self.lock:
            self.sequence += 1
            event: ResearchEvent = {
                "version": 1,
                "id": str(uuid4()),
                "research_id": self.research_id,
                "turn_id": self.turn_id,
                "sequence": self.sequence,
                "at": datetime.now(timezone.utc).isoformat(),
                "task_id": task.id,
                "round": task.round,
                "kind": kind,
                "elapsed_ms": max(0, round((time.monotonic() - task.started) * 1000)),
            }
            if isinstance(topic, str):
                event["topic"] = self.public_text(topic, 2000)
            if tool is not None:
                event["tool"] = tool if tool in PUBLIC_TOOLS else "unknown"
            if isinstance(query, str) and tool in {"tavily_search", "load_skill"}:
                event["query"] = self.public_text(query, 1000)
            if sources is not None:
                safe = [
                    {
                        "title": self.public_text(source["title"], 240),
                        "url": source["url"],
                    }
                    for source in merge_sources(sources)
                    if len(source["url"]) <= 2048
                    and not any(secret in source["url"] for secret in self.secrets)
                ]
                event["source_count"] = len(safe)
                event["sources"] = safe[:50]
            if isinstance(output, str):
                event["output"] = self.public_text(output, 8000)
            self.events.append(event)
            if self.journal and self.identity:
                try:
                    self.journal.append(self.identity, event)
                except Exception as exc:
                    self.storage_failure(exc)
            # Progress transport must not turn otherwise valid research into failure.
            try:
                self.writer({"type": "atlas.research_event", "event": event})
            except Exception:
                pass

    def storage_failure(self, exc: Exception) -> None:
        if not self.journal_failed:
            logger.warning(
                "Research event journal unavailable (%s)", type(exc).__name__
            )
        self.journal_failed = True


_recorder: ContextVar[EventRecorder | None] = ContextVar(
    "atlas_event_recorder", default=None
)
_task: ContextVar[_Task | None] = ContextVar("atlas_research_task", default=None)


@contextmanager
def capture_research_events(research_id: str, turn_id: str):
    """Capture events in the parent node, including failed child invocations."""
    try:
        writer = get_stream_writer()
    except RuntimeError:
        writer = lambda _: None
    recorder = EventRecorder(research_id, turn_id, writer)
    try:
        configurable = get_config().get("configurable", {})
    except RuntimeError:
        configurable = {}
    if configurable.get("run_id") and configurable.get("thread_id"):
        recorder.identity = EventIdentity(
            str(configurable["thread_id"]),
            str(configurable["run_id"]),
            research_id,
            turn_id,
        )
        try:
            recorder.journal = get_event_journal()
            if recorder.journal:
                recorder.sequence = recorder.journal.begin(recorder.identity)
        except Exception as exc:
            recorder.storage_failure(exc)
            recorder.journal = None
    token = _recorder.set(recorder)
    try:
        yield recorder.events
    finally:
        if recorder.journal and recorder.identity:
            try:
                recorder.journal.finish(
                    recorder.identity, recorder.sequence, gap=recorder.journal_failed
                )
            except Exception as exc:
                recorder.storage_failure(exc)
        _recorder.reset(token)


@contextmanager
def researcher_task(call_id: str, topic: str, iteration: int):
    """Give every actual delegation its own identity, including later rounds."""
    recorder = _recorder.get()
    if recorder is None:
        yield
        return
    identity = f"{recorder.research_id}/{recorder.turn_id}/{recorder.capture_id}/{iteration}/{call_id}"
    token = _task.set(_Task(str(uuid5(NAMESPACE_URL, identity)), iteration))
    try:
        emit_research_event("delegated", topic=topic)
        yield
    finally:
        _task.reset(token)


def emit_research_event(kind: EventKind, **details) -> None:
    """Publish only explicitly chosen progress fields within a full-graph task."""
    recorder, task = _recorder.get(), _task.get()
    if recorder is not None and task is not None:
        recorder.record(task, kind, **details)
