"""Real streaming machinery with explicit model substitutes; no provider calls."""

import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

from langchain_core.messages import AIMessageChunk
import pytest
from starlette.testclient import TestClient
from tenacity import wait_none

from deep_research import report_streaming as reports
from deep_research.event_journal import EventIdentity, EventJournal


@pytest.fixture
def capture(tmp_path, monkeypatch):
    identity = EventIdentity(str(uuid4()), str(uuid4()), "research", "turn")
    attempt = str(uuid4())
    path = tmp_path / "reports.sqlite3"
    monkeypatch.setenv("ATLAS_REPORT_EVENT_DB", str(path))
    monkeypatch.setenv("ATLAS_EVENT_DB", str(tmp_path / "research.sqlite3"))
    journal = EventJournal(path)
    seen = []

    def publish(payload):
        assert payload["type"] == "atlas.report_event"
        event = payload["event"]
        assert journal.read(identity, limit=100)["events"][-1] == event
        seen.append(event)

    monkeypatch.setattr(
        reports,
        "get_config",
        lambda: {
            "configurable": {
                "thread_id": identity.thread_id,
                "run_id": identity.run_id,
            },
            "metadata": {"atlas_attempt_id": attempt},
        },
    )
    monkeypatch.setattr(reports, "get_stream_writer", lambda: publish)
    monkeypatch.setattr(reports, "wait_exponential_jitter", lambda: wait_none())
    return SimpleNamespace(
        identity=identity,
        attempt=attempt,
        events=seen,
        journal=journal,
        state={"active_research_id": "research", "active_turn_id": "turn"},
    )


def test_first_paragraph_commits_while_model_is_still_blocked(capture):
    async def check():
        release = asyncio.Event()

        async def stream(_):
            yield AIMessageChunk(content="# 真正文\n\n首段 🌌")
            await release.wait()
            yield AIMessageChunk(content="。\n\n结束。")

        task = asyncio.create_task(
            reports.stream_final_report(
                SimpleNamespace(astream=stream), [], capture.state
            )
        )
        try:
            async with asyncio.timeout(3):
                while not any(event["kind"] == "delta" for event in capture.events):
                    await asyncio.sleep(0.01)
            assert not task.done()
            assert not any(event["kind"] == "finished" for event in capture.events)
            release.set()
            report, ownership = await task
            assert report == "# 真正文\n\n首段 🌌。\n\n结束。"
            assert ownership["report_attempt_id"] == capture.attempt
            assert ownership["report_run_id"] == capture.identity.run_id
            assert (
                ownership["report_writing_attempt_id"]
                == capture.events[0]["writing_attempt_id"]
            )
            assert capture.events[-1]["offset"] == len(report.encode())
        finally:
            release.set()
            await task

    asyncio.run(check())
    page = capture.journal.read(capture.identity)
    assert page["sealed"] and not page["gap"]
    assert page["events"] == capture.events


def test_midstream_retry_has_new_attempt_and_does_not_join_old_text(capture):
    calls = 0

    async def stream(_):
        nonlocal calls
        calls += 1
        if calls == 1:
            yield AIMessageChunk(content="失败草稿")
            raise ConnectionError("private provider error")
        yield AIMessageChunk(content="成功尝试的正文")

    report, ownership = asyncio.run(
        reports.stream_final_report(SimpleNamespace(astream=stream), [], capture.state)
    )
    assert calls == 2 and report == "成功尝试的正文"
    starts = [event for event in capture.events if event["kind"] == "started"]
    assert len({event["writing_attempt_id"] for event in starts}) == 2
    assert len({event["run_id"] for event in capture.events}) == 1
    assert ownership["report_writing_attempt_id"] == starts[-1]["writing_attempt_id"]
    assert [event["kind"] for event in capture.events] == [
        "started",
        "delta",
        "failed",
        "started",
        "delta",
        "finished",
    ]
    assert "private provider error" not in json.dumps(capture.events)


def test_cancelled_writer_closes_stream_without_starting_another_attempt(capture):
    calls = 0
    closed = []

    async def check():
        waiting = asyncio.Event()

        async def stream(_):
            nonlocal calls
            calls += 1
            try:
                yield AIMessageChunk(content="已保存的草稿")
                if calls == 1:
                    waiting.set()
                    await asyncio.Event().wait()
                yield AIMessageChunk(content="不应重新生成")
            finally:
                closed.append(calls)

        task = asyncio.create_task(
            reports.stream_final_report(
                SimpleNamespace(astream=stream),
                [],
                capture.state,
            )
        )
        async with asyncio.timeout(3):
            await waiting.wait()
            while not any(event["kind"] == "delta" for event in capture.events):
                await asyncio.sleep(0.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(check())
    assert calls == 1
    assert closed == [1]
    assert [event["kind"] for event in capture.events] == ["started", "delta", "failed"]
    assert capture.journal.read(capture.identity)["sealed"]


@pytest.mark.parametrize("mode", ["empty", "disconnected", "auth"])
def test_retry_budget_and_empty_output(capture, mode):
    calls = 0

    class AuthError(Exception):
        status_code = 401

    async def stream(_):
        nonlocal calls
        calls += 1
        if mode == "auth":
            raise AuthError()
        if mode == "disconnected":
            raise ConnectionError()
        yield AIMessageChunk(content="")

    with pytest.raises(Exception):
        asyncio.run(
            reports.stream_final_report(
                SimpleNamespace(astream=stream), [], capture.state
            )
        )
    assert calls == (1 if mode == "auth" else 3)
    assert not any(event["kind"] == "finished" for event in capture.events)
    assert capture.journal.read(capture.identity)["sealed"]


def test_reasoning_tool_fields_and_secrets_across_chunks_are_filtered(
    capture, monkeypatch
):
    monkeypatch.setenv("REPORT_TEST_API_KEY", "secret-that-spans-chunks")

    async def stream(_):
        yield AIMessageChunk(
            content=[
                {"type": "reasoning", "text": "PRIVATE REASONING"},
                {"type": "text", "text": "正文 secret-that-"},
            ],
            additional_kwargs={"reasoning_content": "PRIVATE FIELD"},
        )
        yield AIMessageChunk(content="spans-chunks 末尾")

    report, _ = asyncio.run(
        reports.stream_final_report(SimpleNamespace(astream=stream), [], capture.state)
    )
    assert report == "正文 [redacted] 末尾"
    assert "PRIVATE" not in json.dumps(capture.events)
    assert "secret-that" not in json.dumps(capture.events)


def test_storage_and_observer_failures_leave_business_output_usable(
    capture, monkeypatch
):
    monkeypatch.setattr(
        EventJournal,
        "append",
        lambda *args: (_ for _ in ()).throw(OSError("private path")),
    )
    monkeypatch.setattr(
        reports,
        "get_stream_writer",
        lambda: lambda _: (_ for _ in ()).throw(RuntimeError()),
    )

    async def stream(_):
        yield AIMessageChunk(content="可保留的报告")

    result, _ = asyncio.run(
        reports.stream_final_report(SimpleNamespace(astream=stream), [], capture.state)
    )
    assert result == "可保留的报告"
    page = capture.journal.read(capture.identity)
    assert page["gap"] and page["sealed"] and page["last_sequence"] == 3


def test_report_replay_is_separate_from_research_and_rejects_wrong_owner(capture):
    from deep_research.atlas_api import app

    async def stream(_):
        yield AIMessageChunk(content="独立正文")

    asyncio.run(
        reports.stream_final_report(SimpleNamespace(astream=stream), [], capture.state)
    )
    client = TestClient(app)
    path = f"/atlas/threads/{capture.identity.thread_id}/runs/{capture.identity.run_id}"
    query = "?research_id=research&turn_id=turn"
    page = client.get(path + "/report-events" + query).json()
    assert page["events"] == capture.events
    assert client.get(path + "/events" + query).json()["status"] == "missing"
    assert (
        client.get(path + "/report-events?research_id=another&turn_id=turn").status_code
        == 409
    )


def test_two_concurrent_writers_keep_distinct_identities(capture, monkeypatch):
    async def check():
        async def stream(messages):
            yield AIMessageChunk(content=messages[0])
            await asyncio.sleep(0)
            yield AIMessageChunk(content=" 结束")

        # Capture construction happens in each task's native config context.
        from contextvars import ContextVar

        current = ContextVar("test_report_config")
        monkeypatch.setattr(reports, "get_config", current.get)
        monkeypatch.setattr(reports, "get_stream_writer", lambda: lambda _: None)

        async def one(label):
            run = str(uuid4())
            current.set({"configurable": {"thread_id": str(uuid4()), "run_id": run}})
            text, owner = await reports.stream_final_report(
                SimpleNamespace(astream=stream), [label], capture.state
            )
            assert owner["report_run_id"] == run
            return text, owner

        result = await asyncio.gather(one("甲"), one("乙"))
        assert [text for text, _ in result] == ["甲 结束", "乙 结束"]
        assert (
            result[0][1]["report_writing_attempt_id"]
            != result[1][1]["report_writing_attempt_id"]
        )

    asyncio.run(check())
