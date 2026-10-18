"""Final-writer text only, with bounded retries and durable attempt boundaries.

The report journal is a separate namespace from researcher events. A model's
finished event is NOT a committed report: the owning checkpoint decides that.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import logging
import os
from pathlib import Path
import time
from uuid import uuid4

from langgraph.config import get_config, get_stream_writer
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from deep_research.event_journal import EventIdentity, EventJournal, journal_path
from deep_research.workflow_contract import is_research_note

logger = logging.getLogger(__name__)
CHUNK_SIZE = 2048
FLUSH_SECONDS = 0.15
MAX_REPORT_CHARS = 1_000_000
MAX_WRITING_ATTEMPTS = 3


def report_journal_path():
    if configured := os.getenv("ATLAS_REPORT_EVENT_DB"):
        return Path(configured).resolve()
    parent = journal_path()
    return parent.with_name("atlas-report-events.sqlite3") if parent else None


def get_report_journal():
    path = report_journal_path()
    if path is None:
        return None
    days = int(os.getenv("ATLAS_EVENT_RETENTION_DAYS", "30"))
    if not 1 <= days <= 3650:
        raise ValueError("Invalid report retention")
    return EventJournal(path, retention_seconds=days * 86400)


def report_text(chunk):
    """Never read reasoning, tool arguments, metadata, or provider payloads."""
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block["text"]
            for block in content
            if isinstance(block, dict)
            and block.get("type") in {"text", "text_delta", "output_text"}
            and isinstance(block.get("text"), str)
        )
    return ""


class PublicText:
    """Hold partial secret prefixes so redaction also spans provider chunks."""

    def __init__(self):
        self.secrets = tuple(
            value
            for name, value in os.environ.items()
            if value
            and value != "*"
            and name.upper().endswith(("_KEY", "_TOKEN", "_BASE_URL", "_PROXY"))
        )
        self.pending = ""

    def feed(self, text, *, final=False):
        self.pending += text
        for secret in self.secrets:
            self.pending = self.pending.replace(secret, "[redacted]")
        hold = 0
        if not final:
            for secret in self.secrets:
                for length in range(1, min(len(secret), len(self.pending) + 1)):
                    if self.pending.endswith(secret[:length]):
                        hold = max(hold, length)
        cut = len(self.pending) - hold
        result, self.pending = self.pending[:cut], self.pending[cut:]
        return result


@dataclass
class ReportRecorder:
    identity: EventIdentity
    attempt_id: str
    writer: object
    journal: EventJournal | None = None
    sequence: int = 0
    gap: bool = False
    writing_attempt_id: str = ""
    offset: int = 0
    events: list[dict] = field(default_factory=list)

    @classmethod
    def create(cls, state):
        try:
            config = get_config()
            writer = get_stream_writer()
        except RuntimeError:
            config, writer = {}, lambda _: None
        configurable = config.get("configurable", {})
        run_id = str(configurable.get("run_id") or uuid4())
        recorder = cls(
            EventIdentity(
                str(configurable.get("thread_id") or uuid4()),
                run_id,
                state.get("active_research_id", ""),
                state.get("active_turn_id", ""),
            ),
            str(config.get("metadata", {}).get("atlas_attempt_id") or run_id),
            writer,
        )
        if configurable.get("run_id") and configurable.get("thread_id"):
            try:
                recorder.journal = get_report_journal()
                if recorder.journal:
                    recorder.sequence = recorder.journal.begin(recorder.identity)
            except Exception as exc:
                recorder.storage_failure(exc)
                recorder.journal = None
        return recorder

    def storage_failure(self, exc):
        if not self.gap:
            logger.warning("Report journal unavailable (%s)", type(exc).__name__)
        self.gap = True

    def emit(self, kind, **fields):
        self.sequence += 1
        event = {
            "version": 1,
            "id": str(uuid4()),
            **self.identity.public(),
            "attempt_id": self.attempt_id,
            "writing_attempt_id": self.writing_attempt_id,
            "sequence": self.sequence,
            "kind": kind,
            "at": datetime.now(timezone.utc).isoformat(),
            "offset": self.offset,
            **fields,
        }
        if self.journal:
            try:
                self.journal.append(self.identity, event)
            except Exception as exc:
                self.storage_failure(exc)
        # Do not publish secrets or storage/provider exception bodies.
        self.events.append(event)
        try:
            self.writer({"type": "atlas.report_event", "event": event})
        except Exception:
            pass

    def start(self):
        self.writing_attempt_id = str(uuid4())
        self.offset = 0
        self.emit("started")

    def delta(self, text):
        for start in range(0, len(text), CHUNK_SIZE):
            chunk = text[start : start + CHUNK_SIZE]
            self.emit("delta", text=chunk)
            self.offset += len(chunk.encode("utf-8"))

    def close(self):
        if self.journal:
            try:
                self.journal.finish(self.identity, self.sequence, gap=self.gap)
            except Exception as exc:
                self.storage_failure(exc)


def retryable_writer_error(exc):
    # Cancellation and process shutdown must never start a new generation.
    if not isinstance(exc, Exception):
        return False
    # Authentication and invalid requests do not improve when repeated.
    status = getattr(exc, "status_code", None)
    return not (
        isinstance(status, int)
        and 400 <= status < 500
        and status not in {408, 409, 429}
    )


async def _write_attempt(model, messages, recorder):
    public = PublicText()
    parts = []
    pending = ""
    length = 0
    last_flush = time.monotonic()

    def accept(text):
        nonlocal pending, length, last_flush
        length += len(text)
        if length > MAX_REPORT_CHARS:
            raise ValueError("Report exceeds bounded output size")
        parts.append(text)
        pending += text
        if pending and (
            len(pending) >= CHUNK_SIZE or time.monotonic() - last_flush >= FLUSH_SECONDS
        ):
            recorder.delta(pending)
            pending = ""
            last_flush = time.monotonic()

    try:
        if callable(getattr(model, "astream", None)):
            iterator = model.astream(messages).__aiter__()
            task = asyncio.create_task(anext(iterator))
            try:
                while True:
                    done, _ = await asyncio.wait({task}, timeout=FLUSH_SECONDS)
                    if not done:
                        if pending:
                            recorder.delta(pending)
                            pending = ""
                            last_flush = time.monotonic()
                        continue
                    try:
                        chunk = task.result()
                    except StopAsyncIteration:
                        break
                    accept(public.feed(report_text(chunk)))
                    task = asyncio.create_task(anext(iterator))
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                if callable(getattr(iterator, "aclose", None)):
                    await iterator.aclose()
        else:
            # Compatibility for standalone non-streaming models; no fake tokens.
            accept(public.feed(report_text(await model.ainvoke(messages))))
        accept(public.feed("", final=True))
        report = "".join(parts).strip()
        if not is_research_note(report):
            raise ValueError("Empty or failed final report")
        return report
    finally:
        if pending:
            recorder.delta(pending)


async def stream_final_report(model, messages, state, *, review=None):
    """Three application attempts; SDK retries remain bounded and separate.

    RunnableRetry deliberately does not retry streams. Each replay of the
    generation therefore gets its own UUID here, including midstream failures.
    """
    recorder = ReportRecorder.create(state)
    generated = 0
    try:
        for revision in range(2):
            if generated >= MAX_WRITING_ATTEMPTS:
                raise ValueError("Writing budget exhausted before revision")
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(MAX_WRITING_ATTEMPTS - generated),
                wait=wait_exponential_jitter(),
                retry=retry_if_exception(retryable_writer_error),
                reraise=True,
            ):
                with attempt:
                    generated += 1
                    recorder.start()
                    try:
                        report = await _write_attempt(model, messages, recorder)
                    except BaseException:
                        recorder.emit("failed")
                        raise
                    recorder.emit("finished", sha256=hashlib.sha256(report.encode()).hexdigest())
                if not attempt.retry_state.outcome.failed:
                    break
            try:
                revised_messages = await review(report, recorder.writing_attempt_id) if review else None
                if revised_messages is not None and revision:
                    raise ValueError("Report failed review after the single revision")
            except BaseException:
                recorder.emit("failed")
                raise
            if revised_messages is None:
                return report, {
                    "report_run_id": recorder.identity.run_id,
                    "report_turn_id": recorder.identity.turn_id,
                    "report_attempt_id": recorder.attempt_id,
                    "report_writing_attempt_id": recorder.writing_attempt_id,
                }
            messages = revised_messages
    finally:
        recorder.close()
