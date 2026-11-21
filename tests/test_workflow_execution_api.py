"""Opt-in M3 production HTTP acceptance, native scheduling and restart evidence."""

import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest

from deep_research.workflow_definition import WorkflowSelection
from tests.test_workflow_execution import document
from tests.test_workflow_factory_api import TOPIC
from tests.test_workflow_factory_api import NativeFixture as BaseFixture

pytestmark = pytest.mark.skipif(
    os.getenv("ATLAS_WORKFLOW_M3_API") != "1",
    reason="Opt in with ATLAS_WORKFLOW_M3_API=1",
)


class NativeFixture(BaseFixture):
    PARENT = ".local/graph-canvas-m3"
    SERVER = "tests/atlas_workflow_execution_server.py"
    IDENTITY = "/m3/identity"

    def publish(self, value=None, *, workflow_id=None):
        draft = (
            self.get(f"/atlas/workflows/{workflow_id}")
            if workflow_id
            else self.post(
                "/atlas/workflows",
                {
                    "request_id": str(uuid4()),
                    "name": "M3 Native fixture",
                    "source": {"kind": "template", "template_id": "standard_research"},
                },
            )
        )
        workflow_id = draft["workflow_id"]
        if value is not None:
            response = self.client.put(
                f"/atlas/workflows/{workflow_id}/draft",
                json={
                    "expected_edit_version": draft["edit_version"],
                    "document": value.model_dump(mode="json"),
                },
            )
            response.raise_for_status()
            draft = response.json()
        return self.post(
            f"/atlas/workflows/{workflow_id}/publish",
            {
                "request_id": str(uuid4()),
                "expected_edit_version": draft["edit_version"],
                "note": "Native M3 test",
            },
        )

    def submission(
        self,
        revision=None,
        topic=TOPIC,
        *,
        thread=None,
        research=None,
        previous=None,
        selection=None,
    ):
        if thread is None:
            thread = str(uuid4())
            self.post("/threads", {"thread_id": thread})
        turn = str(uuid4())
        body = {
            "research_id": research or str(uuid4()),
            "text": topic,
            "expected_turn_id": previous,
        }
        if revision:
            body["workflow_ref"] = {
                key: revision[key] for key in ("workflow_id", "revision_id")
            }
        if selection:
            body["selection"] = selection
        return {
            "thread": thread,
            "turn": turn,
            "path": f"/atlas/threads/{thread}/submissions/{turn}",
            "body": body,
        }

    def events(self, submission, receipt=None):
        receipt = receipt or self.get(submission["path"])
        events, after = [], 0
        while True:
            page = self.get(
                f"/atlas/threads/{submission['thread']}/runs/{receipt['run_id']}/workflow-events"
                f"?research_id={receipt['research_id']}&turn_id={receipt['turn_id']}&attempt_id={receipt['attempt_id']}&after={after}&limit=3"
            )
            events += page["events"]
            if not page["has_more"]:
                assert [event["sequence"] for event in events] == list(
                    range(1, len(events) + 1)
                )
                return events, page
            after = page["next_sequence"]

    def state(self, submission):
        result = super().state(submission)
        self.observed_states[submission["thread"]]["workflow_binding"] = result[
            "values"
        ].get("workflow_binding")
        return result


@pytest.fixture
def native(request):
    fixture = NativeFixture(request.node.name)
    try:
        fixture.start()
        yield fixture
    finally:
        fixture.finish()


def assert_report(f, submission, revision):
    receipt = f.completed(submission)
    values = f.state(submission)["values"]
    assert values["research_status"] == "succeeded", values.get("research_errors")
    assert values["report_research_id"] == submission["body"]["research_id"]
    assert values["report_turn_id"] == submission["turn"]
    assert values["report_run_id"] == receipt["run_id"]
    assert values["report_attempt_id"] == receipt["attempt_id"]
    assert values["workflow_binding"] == receipt["workflow_binding"]
    assert (
        values["workflow_binding"]["workflow_ref"]["revision_id"]
        == revision["revision_id"]
    )
    assert "API 测试替身" in values["final_report"]
    assert values["notes"] and values["sources"]
    return values


def test_native_publication_clarification_paths_and_read_only_replay(native):
    f = native
    first = f.publish()
    waiting = f.submission(first, "比较两种构建")
    f.post(waiting["path"], waiting["body"])
    f.completed(waiting)
    assert f.state(waiting)["values"]["research_status"] == "awaiting_input"
    second = f.publish(document(), workflow_id=first["workflow_id"])
    conflict = f.submission(
        second,
        thread=waiting["thread"],
        research=waiting["body"]["research_id"],
        previous=waiting["turn"],
    )
    response = f.client.post(conflict["path"], json=conflict["body"])
    assert (
        response.status_code == 409
        and response.json()["reason"] == "workflow_binding_conflict"
    )
    answer = f.submission(
        thread=waiting["thread"],
        research=waiting["body"]["research_id"],
        previous=waiting["turn"],
    )
    extended = f.submission(second)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all(
            result["run_id"]
            for result in pool.map(
                lambda s: f.post(s["path"], s["body"]), (answer, extended)
            )
        )
    old, new = assert_report(f, answer, first), assert_report(f, extended, second)
    assert old["organized_notes"] is None
    assert new["organized_notes"].startswith("[M3 organized]")
    assert old["notes"] == new["notes"] and old["raw_notes"] == new["raw_notes"]
    assert (
        old["sources"] == new["sources"]
        and old["source_evidence"] == new["source_evidence"]
    )
    assert (
        f.counts(extended)["optimize_plan"] == f.counts(extended)["organize_notes"] == 1
    )
    assert f.counts(answer)["optimize_plan"] == 0
    assert all(
        item["detail"]["received_optimized"]
        for item in f.audit(extended, "call")
        if item["name"] == "supervisor"
    )
    assert all(
        item["detail"]["received_organized"]
        for item in f.audit(extended, "call")
        if item["name"] == "writer"
    )
    events, page = f.events(extended)
    assert page["sealed"] and not page["gap"]
    assert [event["node_id"] for event in events if event["kind"] == "completed"] == [
        node["id"] for node in second["document"]["definition"]["nodes"][1:-1]
    ]
    for event in events:
        assert event["workflow_ref"]["revision_id"] == second["revision_id"]
    third = f.publish(
        document(clarify=False, extensions=0), workflow_id=first["workflow_id"]
    )
    reduced = f.submission(third)
    f.post(reduced["path"], reduced["body"])
    assert_report(f, reduced, third)
    assert (
        f.counts(reduced)["clarify"]
        == f.counts(reduced)["optimize_plan"]
        == f.counts(reduced)["organize_notes"]
        == 0
    )
    for submission, count in ((answer, 2), (extended, 1), (reduced, 1)):
        before = f.counts(submission)
        for _ in range(2):
            f.state(submission)
            f.events(submission)
            f.get(submission["path"])
            history = f.post(f"/threads/{submission['thread']}/history", {"limit": 100})
            bindings = [
                item["values"].get("workflow_binding")
                for item in history
                if item["values"].get("workflow_binding")
            ]
            assert len({item["workflow_ref"]["revision_id"] for item in bindings}) == 1
        assert len(f.runs(submission)) == count and f.counts(submission) == before


@pytest.mark.parametrize(
    "fault", ["exit-in-transaction", "exit-after-intent", "lose-response"]
)
def test_native_acceptance_faults_and_lost_response_never_duplicate_runs(native, fault):
    f = native
    revision = f.publish(document())
    submission = f.submission(revision)
    marker = f.directory / fault
    marker.write_text("fault", encoding="utf-8")
    try:
        response = f.client.post(submission["path"], json=submission["body"])
        assert response.status_code == 503
    except httpx.HTTPError:
        assert fault != "lose-response"
    if fault != "lose-response":
        # The fault exits the server itself. Wait for the Windows venv launcher
        # to observe that exit instead of racing it with a forced termination.
        assert f.process.wait(timeout=10) == (
            86 if fault == "exit-in-transaction" else 87
        )
        f.stop()
        marker.unlink(missing_ok=True)
        with sqlite3.connect(f.directory / "submissions.sqlite3") as db:
            count = db.execute(
                "SELECT COUNT(*) FROM workflow_thread_bindings"
            ).fetchone()[0]
            assert count == (0 if fault == "exit-in-transaction" else 1)
        f.start()
    first = f.post(submission["path"], submission["body"])
    f.post(submission["path"], submission["body"])
    values = assert_report(f, submission, revision)
    assert values["report_run_id"] == first["run_id"]
    assert len(f.runs(submission)) == 1
    assert f.counts(submission)["writer"] == f.counts(submission)["search"] == 1
    assert len({row["run_id"] for row in f.audit(submission, "dispatch")}) == 1


@pytest.mark.parametrize(
    "point,safe",
    [
        ("clarify", True),
        ("brief", True),
        ("writer", True),
        ("optimize_plan", False),
        ("organize_notes", False),
        ("search", False),
    ],
)
def test_native_restart_recovers_only_safe_bound_checkpoints(native, point, safe):
    f = native
    revision = f.publish(document())
    f.pause(point)
    submission = f.submission(revision)
    accepted = f.post(submission["path"], submission["body"])
    f.entered(point)
    original = f.state(submission)
    f.stop()
    f.release(point)
    (f.directory / "configuration-revision").write_text("v2", encoding="utf-8")
    f.start()
    receipt = f.get(submission["path"])
    assert receipt["status"] == "interrupted", receipt
    assert receipt["recovery"]["allowed"] is safe, receipt
    events, page = f.events(submission, receipt)
    assert events and page["gap"] and page["unconfirmed_before_sequence"] == len(events)
    assert receipt["workflow_binding"] == accepted["workflow_binding"]
    assert receipt["configuration"] == original["values"]["effective_config"]
    before = f.counts(submission)
    if safe:
        path = submission["path"] + f"/recoveries/{uuid4()}"
        body = {
            "research_id": submission["body"]["research_id"],
            "parent_run_id": receipt["run_id"],
            "checkpoint_id": receipt["recovery"]["checkpoint_id"],
        }
        recovered = f.post(path, body)
        assert f.post(path, body)["run_id"] == recovered["run_id"]
        values = assert_report(f, submission, revision)
        assert values["effective_config"] == receipt["configuration"]
        assert f.counts(submission)[point] == before[point] + 1
        if point == "writer":
            assert f.counts(submission)["search"] == before["search"]
            assert f.counts(submission)["organize_notes"] == before["organize_notes"]
        assert f.audit(submission, "dispatch")[-1]["detail"]["input_is_null"] is True
        assert (
            f.audit(submission, "dispatch")[-1]["detail"]["checkpoint_id"]
            == body["checkpoint_id"]
        )
        assert len(f.runs(submission)) == 2
    else:
        assert receipt["recovery"]["reason"] == "research_node_not_resumable"
        assert len(f.runs(submission)) == 1 and f.counts(submission) == before


def test_native_missing_implementation_rejects_before_run_but_preserves_history(native):
    f = native
    revision = f.publish(document())
    f.pause("brief")
    existing = f.submission(revision)
    f.post(existing["path"], existing["body"])
    f.entered("brief")
    f.stop()
    (f.directory / "missing-plan").write_text("missing", encoding="utf-8")
    f.start()
    receipt = f.get(existing["path"])
    assert (
        not receipt["recovery"]["allowed"]
        and receipt["reason"] == "node_implementation_unavailable"
    )
    assert (
        f.state(existing)["values"]["workflow_binding"]["workflow_ref"]["revision_id"]
        == revision["revision_id"]
    )
    assert (
        f.get(
            f"/atlas/workflows/{revision['workflow_id']}/revisions/{revision['revision_id']}"
        )
        == revision
    )
    other = f.submission(revision)
    response = f.client.post(other["path"], json=other["body"])
    assert (
        response.status_code == 503
        and response.json()["reason"] == "node_implementation_unavailable"
    )
    assert f.runs(other) == []
    assert len(f.runs(existing)) == 1


def test_native_workflow_defaults_isolate_six_roles_and_skills(native):
    f = native
    catalog = f.get("/atlas/config")["catalog"]
    defaults = catalog["defaults"]
    roles, identifiers = list(defaults), list(defaults.values())
    selection_a = {
        "version": 1,
        "models": defaults,
        "skills": {"mode": "manual", "allowed": []},
    }
    selection_b = {
        "version": 1,
        "models": dict(zip(roles, identifiers[1:] + identifiers[:1])),
        "skills": {"mode": "manual", "allowed": [catalog["skills"][0]["name"]]},
    }
    submissions = []
    for selection in (selection_a, selection_b):
        value = document()
        value.definition.defaults.selection = WorkflowSelection.model_validate(
            selection
        )
        revision = f.publish(value)
        submissions.append((f.submission(revision), revision, selection))
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(
            pool.map(lambda pair: f.post(pair[0]["path"], pair[0]["body"]), submissions)
        )
    for submission, revision, selection in submissions:
        values = assert_report(f, submission, revision)
        assert values["effective_config"]["selection"] == selection
        assert (
            sorted(values["effective_config"]["skill_revisions"])
            == selection["skills"]["allowed"]
        )
        assert all(
            row["detail"].get("selection") == selection
            for row in f.audit(submission, "call")
        )
    assert submissions[0][2] != submissions[1][2]


def test_native_legacy_payload_null_reference_and_upgrade_lock(native):
    f = native
    legacy = f.submission()
    legacy["body"]["workflow_ref"] = None
    accepted = f.post(legacy["path"], legacy["body"])
    f.completed(legacy)
    omitted = {
        key: value for key, value in legacy["body"].items() if key != "workflow_ref"
    }
    assert f.post(legacy["path"], omitted)["run_id"] == accepted["run_id"]
    assert f.state(legacy)["values"]["research_status"] == "succeeded"
    assert "workflow_binding" not in accepted
    revision = f.publish(document())
    upgrade = f.submission(revision, thread=legacy["thread"], previous=legacy["turn"])
    response = f.client.post(upgrade["path"], json=upgrade["body"])
    assert (
        response.status_code == 409
        and response.json()["reason"] == "legacy_workflow_locked"
    )
    assert len(f.runs(legacy)) == 1


def test_native_archive_blocks_new_bindings_but_allows_original_clarification(native):
    f = native
    revision = f.publish(document())
    waiting = f.submission(revision, "比较两种构建")
    f.post(waiting["path"], waiting["body"])
    f.completed(waiting)
    draft = f.get(f"/atlas/workflows/{revision['workflow_id']}")
    f.post(
        f"/atlas/workflows/{revision['workflow_id']}/archive",
        {"expected_edit_version": draft["edit_version"]},
    )
    new = f.submission(revision)
    response = f.client.post(new["path"], json=new["body"])
    assert (
        response.status_code == 409 and response.json()["reason"] == "workflow_archived"
    )
    assert f.runs(new) == []
    answer = f.submission(
        thread=waiting["thread"],
        research=waiting["body"]["research_id"],
        previous=waiting["turn"],
    )
    f.post(answer["path"], answer["body"])
    assert_report(f, answer, revision)
    assert len(f.runs(answer)) == 2
