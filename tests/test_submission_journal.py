"""Durable identities and checkpoint evidence; no real provider calls."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import sqlite3
from types import SimpleNamespace
from uuid import uuid4

from langchain_core.messages import HumanMessage
import pytest
import httpx

from deep_research import submission_journal as module
from deep_research.atlas_runtime import submissions_enabled
from deep_research.submission_api import recovery_boundary
from deep_research.submission_journal import (
    SubmissionConflict,
    SubmissionJournal,
    state_digest,
)


@pytest.fixture
def journal(tmp_path):
    return SubmissionJournal(tmp_path / "submissions.sqlite3")


def reserve(journal):
    return journal.reserve(
        str(uuid4()),
        str(uuid4()),
        {"research_id": str(uuid4()), "text": "研究问题", "expected_turn_id": None},
    )


def test_same_submission_commits_one_identity_even_under_concurrent_acceptance(journal):
    thread, turn = str(uuid4()), str(uuid4())
    payload = {"research_id": "study", "text": "Question", "expected_turn_id": None}
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(
            pool.map(lambda _: journal.reserve(thread, turn, payload), range(24))
        )
    assert len({record["attempts"][0]["run_id"] for record in records}) == 1
    assert len(journal.get(thread, turn)["attempts"]) == 1
    assert journal.get(thread, turn)["attempts"][0]["owner_id"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("text", "Changed"),
        ("research_id", "other"),
        ("expected_turn_id", "another-turn"),
    ],
)
def test_reusing_turn_with_changed_payload_is_rejected(journal, field, value):
    record = reserve(journal)
    with pytest.raises(SubmissionConflict, match="payload_conflict"):
        journal.reserve(
            record["thread_id"], record["turn_id"], {**record["payload"], field: value}
        )
    assert (
        journal.get(record["thread_id"], record["turn_id"])["payload"]
        == record["payload"]
    )


def test_another_process_cannot_enter_started_attempt(journal, monkeypatch):
    record = reserve(journal)
    attempt = record["attempts"][0]
    journal.enter_node(attempt["run_id"], record["thread_id"], "prepare_research", {})
    monkeypatch.setattr(module, "INSTANCE_ID", "different-process")
    with pytest.raises(SubmissionConflict, match="execution_requires_recovery"):
        journal.enter_node(
            attempt["run_id"], record["thread_id"], "prepare_research", {}
        )


def test_recovery_id_is_durable_and_competing_attempt_rejected(journal):
    record = reserve(journal)
    parent = record["attempts"][0]["run_id"]
    attempt = str(uuid4())
    first = journal.reserve_recovery(
        record, attempt, parent, "checkpoint", "final_report_generation"
    )
    second = SubmissionJournal(journal.path).reserve_recovery(
        record, attempt, parent, "checkpoint", "final_report_generation"
    )
    assert first["attempts"] == second["attempts"]
    with pytest.raises(SubmissionConflict, match="attempt_conflict"):
        journal.reserve_recovery(
            record, str(uuid4()), parent, "checkpoint", "final_report_generation"
        )
    with pytest.raises(SubmissionConflict, match="payload_conflict"):
        journal.reserve_recovery(
            record, attempt, parent, "another-checkpoint", "final_report_generation"
        )


def test_recovery_entry_cannot_silently_start_a_different_node(journal):
    record = reserve(journal)
    record = journal.reserve_recovery(
        record,
        str(uuid4()),
        record["attempts"][0]["run_id"],
        "checkpoint",
        "final_report_generation",
    )
    with pytest.raises(SubmissionConflict, match="checkpoint_changed"):
        journal.enter_node(
            record["attempts"][-1]["run_id"],
            record["thread_id"],
            "supervisor_subgraph",
            {
                "active_turn_id": record["turn_id"],
                "active_research_id": record["research_id"],
            },
        )


def test_message_digest_matches_native_json_representation():
    message = HumanMessage(content="Question", id="turn")
    assert state_digest({"messages": [message]}) == state_digest(
        {"messages": [message.model_dump()]}
    )


def snapshot_fixture(journal, node="final_report_generation", phase="writing"):
    record = reserve(journal)
    state = {
        "active_research_id": record["research_id"],
        "active_turn_id": record["turn_id"],
        "research_status": "running",
        "research_phase": phase,
        "notes": ["Verified notes"],
    }
    journal.enter_node(
        record["attempts"][0]["run_id"], record["thread_id"], node, state
    )
    record = journal.get(record["thread_id"], record["turn_id"])
    snapshot = SimpleNamespace(
        values=state,
        next=(node,),
        config={"configurable": {"checkpoint_id": str(uuid4())}},
        metadata={"run_id": record["attempts"][0]["run_id"]},
    )
    return record, snapshot


@pytest.mark.parametrize("node,phase", module.SAFE_NODES.items())
def test_only_matching_verified_parent_boundary_is_recoverable(journal, node, phase):
    record, snapshot = snapshot_fixture(journal, node, phase)
    assert recovery_boundary(record, snapshot)["allowed"]


@pytest.mark.parametrize("damage", ["turn", "run", "state", "next", "missing"])
def test_stale_or_incomplete_checkpoint_is_not_recoverable(journal, damage):
    record, snapshot = snapshot_fixture(journal)
    if damage == "turn":
        snapshot.values["active_turn_id"] = "other"
    elif damage == "run":
        snapshot.metadata["run_id"] = "other"
    elif damage == "state":
        snapshot.values["notes"] = ["Other notes"]
    elif damage == "next":
        snapshot.next = ("final_report_generation", "supervisor_subgraph")
    else:
        snapshot.config = None
    assert not recovery_boundary(record, snapshot)["allowed"]


def test_interrupted_research_subgraph_requires_a_new_study(journal):
    record, snapshot = snapshot_fixture(journal, "supervisor_subgraph", "research")
    assert recovery_boundary(record, snapshot) == {
        "allowed": False,
        "reason": "research_node_not_resumable",
    }


def test_nonpersistent_fixture_does_not_advertise_recovery(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_DISABLE_FILE_PERSISTENCE", "true")
    assert not submissions_enabled()


def test_completed_checkpoint_is_retained_when_another_turn_is_accepted(journal):
    first = reserve(journal)
    journal.confirm_completed(first["attempts"][0]["run_id"], "completed-checkpoint")
    journal.reserve(
        first["thread_id"],
        str(uuid4()),
        {"research_id": "next", "text": "next", "expected_turn_id": first["turn_id"]},
    )
    restored = SubmissionJournal(journal.path).get(first["thread_id"], first["turn_id"])
    assert restored["attempts"][0]["completed_checkpoint"] == "completed-checkpoint"


def test_recovery_rejects_a_changed_model_configuration(journal):
    record, snapshot = snapshot_fixture(journal)
    snapshot.values["effective_config"] = {"models": [{"model": "different"}]}
    record["attempts"][0]["state_hash"] = state_digest(snapshot.values)
    assert recovery_boundary(record, snapshot) == {
        "allowed": False,
        "reason": "configuration_changed",
    }


def test_schema_migration_preserves_original_run_and_recovery_identity(journal):
    record = reserve(journal)
    with sqlite3.connect(journal.path) as db:
        db.execute("ALTER TABLE attempts DROP COLUMN completed_checkpoint")
        db.execute("PRAGMA user_version=1")
    restored = journal.get(record["thread_id"], record["turn_id"])
    assert restored["attempts"] == record["attempts"]


def test_empty_database_setting_uses_the_default_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ATLAS_SUBMISSION_DB", "")
    monkeypatch.setattr(module, "submissions_enabled", lambda: True)
    assert (
        module.get_submission_journal().path
        == tmp_path / ".langgraph_api/atlas-submissions.sqlite3"
    )


def test_acceptance_order_survives_a_wall_clock_adjustment(journal, monkeypatch):
    first = reserve(journal)
    monkeypatch.setattr(module.time, "time", lambda: 1)
    second_turn = str(uuid4())
    journal.reserve(
        first["thread_id"],
        second_turn,
        {"research_id": "next", "text": "next", "expected_turn_id": first["turn_id"]},
    )
    assert journal.latest(first["thread_id"])["turn_id"] == second_turn


def test_storage_version_failure_is_not_reported_as_a_definite_input_rejection(
    monkeypatch,
):
    from deep_research import submission_api
    from deep_research.atlas_api import app

    def unavailable():
        raise ValueError("Private storage diagnostic")

    monkeypatch.setattr(submission_api, "get_submission_journal", unavailable)

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://fixture"
        ) as client:
            return await client.post(
                f"/atlas/threads/{uuid4()}/submissions/{uuid4()}", json={}
            )

    response = asyncio.run(request())
    assert response.status_code == 503
    assert response.json() == {"reason": "submission_temporarily_unavailable"}
