"""Durable progress is tested independently of model calls and graph execution."""

import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

import pytest
from starlette.testclient import TestClient

from deep_research import atlas_api, event_journal, research_events
from deep_research.event_journal import EventIdentity, EventJournal


@pytest.fixture
def identity():
    return EventIdentity(str(uuid4()), str(uuid4()), "research-a", "turn-a")


@pytest.fixture
def journal(tmp_path, monkeypatch):
    path = tmp_path / "progress.sqlite3"
    monkeypatch.setenv("ATLAS_EVENT_DB", str(path))
    return EventJournal(path)


def record(identity, count=3):
    with patch.object(
        research_events,
        "get_config",
        return_value={
            "configurable": {"thread_id": identity.thread_id, "run_id": identity.run_id}
        },
    ):
        with research_events.capture_research_events(
            identity.research_id, identity.turn_id
        ) as events:
            with research_events.researcher_task("call", "Public topic", 1):
                for _ in range(count - 1):
                    research_events.emit_research_event(
                        "tool_started", tool="tavily_search", query="Public query"
                    )
        return events


def test_committed_before_streaming_and_observer_failure_is_harmless(journal, identity):
    seen = []

    def writer(payload):
        event = payload["event"]
        assert journal.read(identity)["events"][-1] == event
        seen.append(event)
        raise RuntimeError("disconnected observer")

    with patch.object(research_events, "get_stream_writer", return_value=writer):
        events = record(identity)
    result = journal.read(identity)
    assert result["events"] == events == seen
    assert result["sealed"] and not result["gap"]


def test_hard_process_exit_preserves_unsealed_events(journal, identity):
    script = """
import json, os
from unittest.mock import patch
from deep_research import research_events as r
identity = json.loads(os.environ['ATLAS_TEST_IDENTITY'])
with patch.object(r, 'get_config', return_value={'configurable': identity}):
    with r.capture_research_events(identity['research_id'], identity['turn_id']):
        with r.researcher_task('call', 'Before crash', 1):
            r.emit_research_event('tool_started', tool='tavily_search', query='Safe query')
            os._exit(17)
"""
    env = {
        **os.environ,
        "ATLAS_TEST_IDENTITY": json.dumps(identity.public()),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
    }
    result = subprocess.run(
        [sys.executable, "-c", script], env=env, capture_output=True, timeout=30
    )
    assert result.returncode == 17, result.stderr.decode(errors="replace")
    # New object and connection, no finalizer or checkpoint from the dead process.
    recovered = EventJournal(journal.path).read(identity)
    assert [event["kind"] for event in recovered["events"]] == [
        "delegated",
        "tool_started",
    ]
    assert not recovered["sealed"]
    assert recovered["gap"] and recovered["unconfirmed_before_sequence"] == 2
    assert recovered["last_sequence"] == 2


def test_pages_and_resume_attempts_keep_order_and_distinct_tasks(journal, identity):
    first = record(identity, 4)
    second = record(identity, 2)
    assert [e["sequence"] for e in second] == [5, 6]
    assert first[0]["task_id"] != second[0]["task_id"]
    page = journal.read(identity, limit=2)
    found = list(page["events"])
    while page["has_more"]:
        page = journal.read(identity, page["next_sequence"], 2, page["journal_id"])
        found.extend(page["events"])
    assert found == first + second
    assert page["next_sequence"] == 6
    assert page["unconfirmed_before_sequence"] == 4
    reset = journal.read(identity, 100, journal_id=str(uuid4()))
    assert reset["reset"] and reset["gap"]
    assert reset["events"] == first + second


def test_failed_append_is_visible_without_failing_research(journal, identity):
    original = EventJournal.append

    def sometimes_fail(self, identity, event):
        if event["sequence"] == 2:
            raise OSError("PRIVATE STORAGE ERROR")
        return original(self, identity, event)

    with patch.object(EventJournal, "append", sometimes_fail):
        events = record(identity)
    result = journal.read(identity)
    assert len(events) == 3
    assert [e["sequence"] for e in result["events"]] == [1, 3]
    assert result["sealed"] and result["gap"]
    assert "PRIVATE" not in json.dumps(result)


def test_final_append_failure_keeps_high_watermark(journal, identity):
    original = EventJournal.append
    with patch.object(
        EventJournal,
        "append",
        lambda self, key, event: original(self, key, event)
        if event["sequence"] < 3
        else (_ for _ in ()).throw(OSError("offline")),
    ):
        record(identity)
    page = journal.read(identity, after=2)
    assert page["events"] == [] and page["next_sequence"] == 3
    assert page["gap"] and not page["has_more"]


def test_storage_unavailable_still_emits_progress(journal, identity):
    with patch.object(
        research_events, "get_event_journal", side_effect=OSError("disk")
    ):
        events = record(identity)
    assert len(events) == 3
    assert journal.read(identity)["status"] == "missing"


@pytest.mark.parametrize("attempt", range(5))
def test_parallel_runs_are_isolated(journal, identity, attempt):
    keys = [identity, EventIdentity(str(uuid4()), str(uuid4()), "research-b", "turn-b")]
    gate = Barrier(len(keys))
    # Each thread uses its own ContextVar recorder. Patch the context getter per
    # thread via a real RunnableConfig context, avoiding a process-global mock.
    from langchain_core.runnables.config import var_child_runnable_config

    def run(key):
        token = var_child_runnable_config.set(
            {"configurable": {"thread_id": key.thread_id, "run_id": key.run_id}}
        )
        try:
            gate.wait(timeout=5)
            with research_events.capture_research_events(key.research_id, key.turn_id):
                with research_events.researcher_task("same-call", "Topic", 1):
                    research_events.emit_research_event(
                        "completed", output="Safe notes"
                    )
        finally:
            var_child_runnable_config.reset(token)

    with (
        patch.object(research_events, "get_stream_writer", return_value=lambda _: None),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        list(pool.map(run, keys))
    for key in keys:
        page = journal.read(key)
        assert len(page["events"]) == 2
        assert {e["research_id"] for e in page["events"]} == {key.research_id}
        assert [e["sequence"] for e in page["events"]] == [1, 2]


def test_retention_tombstone_then_missing_is_explicit(journal, identity):
    record(identity)
    now = event_journal.time.time()
    with patch.object(event_journal.time, "time", return_value=now + 31 * 86400):
        result = journal.read(identity)
    assert result["status"] == "expired" and result["gap"]
    assert not result["events"] and result["last_sequence"] == 3
    with patch.object(event_journal.time, "time", return_value=now + 61 * 86400):
        assert journal.read(identity)["status"] == "missing"


def test_schema_upgrade_keeps_sealed_history_and_marks_old_open_capture(
    journal, identity
):
    events = record(identity)
    with sqlite3.connect(journal.path) as db:
        db.execute("ALTER TABLE event_runs DROP COLUMN owner_id")
        db.execute("ALTER TABLE event_runs DROP COLUMN unconfirmed_before")
        db.execute("PRAGMA user_version=1")
    upgraded = EventJournal(journal.path).read(identity)
    assert upgraded["events"] == events
    assert upgraded["sealed"] and not upgraded["gap"]
    with sqlite3.connect(journal.path) as db:
        db.execute("UPDATE event_runs SET sealed=0")
    interrupted = journal.read(identity)
    assert interrupted["events"] == events
    assert interrupted["gap"] and interrupted["unconfirmed_before_sequence"] == 3


def test_replay_api_validates_scope_pages_and_hides_storage_errors(journal, identity):
    record(identity)
    path = f"/atlas/threads/{identity.thread_id}/runs/{identity.run_id}/events"
    params = {"research_id": identity.research_id, "turn_id": identity.turn_id}
    with TestClient(atlas_api.app) as client:
        response = client.get(path, params={**params, "limit": 1})
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["has_more"]
        assert len(response.json()["events"]) == 1
        assert (
            client.get(path, params={**params, "turn_id": "wrong"}).status_code == 409
        )
        assert client.get(path, params={**params, "after": -1}).status_code == 400
        assert client.get(path, params={**params, "limit": 101}).status_code == 400
        assert client.post(path, params=params).status_code == 405
        with patch.object(EventJournal, "read", side_effect=OSError("PRIVATE PATH")):
            response = client.get(path, params=params)
        assert response.status_code == 503
        assert "PRIVATE" not in response.text


def test_no_disk_journal_for_default_nonpersistent_fixture(monkeypatch):
    monkeypatch.delenv("ATLAS_EVENT_DB", raising=False)
    monkeypatch.setenv("LANGGRAPH_DISABLE_FILE_PERSISTENCE", "true")
    assert event_journal.get_event_journal() is None
