"""Opt-in M0 native HTTP/restart evidence; every process and database is isolated."""

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from tests.atlas_workflow_factory import CORE, EXTENDED, RevisionStore

pytestmark = pytest.mark.skipif(
    os.getenv("ATLAS_WORKFLOW_M0_API") != "1",
    reason="Opt in with ATLAS_WORKFLOW_M0_API=1",
)
ROOT = Path(__file__).resolve().parents[1]
TOPIC = "比较 Python 3.13 free-threaded 与默认构建。"


class NativeFixture:
    def __init__(self, test_name):
        self.test_name = test_name
        self.observed_runs = {}
        self.observed_states = {}
        parent = ROOT / ".local" / "atlas-workflow-m0"
        parent.mkdir(parents=True, exist_ok=True)
        self.directory = Path(tempfile.mkdtemp(prefix="case-", dir=parent))
        self.fixture_id = str(uuid4())
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.client = httpx.Client(
            base_url=f"http://127.0.0.1:{self.port}", trust_env=False, timeout=25
        )
        self.process = None
        self.server_pid = None
        self.log = None
        self.instances = []
        self.last_identity = {}

    def start(self):
        self.log = (self.directory / "server.log").open("ab")
        self.process = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "tests/atlas_workflow_server.py"),
                "--port",
                str(self.port),
                "--directory",
                str(self.directory),
                "--fixture-id",
                self.fixture_id,
            ],
            cwd=ROOT,
            stdout=self.log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise AssertionError(
                    (self.directory / "server.log").read_text(
                        encoding="utf-8", errors="replace"
                    )[-8000:]
                )
            try:
                identity = self.get("/m0/identity")
                if identity["fixture_id"] == self.fixture_id:
                    # Windows venv python.exe may be a launcher with a child PID.
                    # The random fixture identity associates this server with us.
                    self.server_pid = identity["pid"]
                    assert (
                        identity["substitutes"]
                        and identity["submission_contract"]
                        and identity["compatible_runtime"]
                    )
                    assert identity["instance_id"] not in self.instances
                    self.instances.append(identity["instance_id"])
                    return
            except (httpx.HTTPError, KeyError):
                pass
            time.sleep(0.1)
        raise AssertionError(f"M0 server did not start: {self.directory}")

    def stop(self):
        if self.process is not None:
            if self.process.poll() is None:
                try:
                    self.last_identity = self.get("/m0/identity")
                except httpx.HTTPError:
                    pass
                if self.server_pid is not None and self.server_pid != self.process.pid:
                    try:
                        os.kill(self.server_pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                # Stop our venv launcher as well as its identified server process.
                self.process.kill()
            self.process.wait(timeout=10)
            self.process = None
            self.server_pid = None
        if self.log is not None:
            self.log.close()
            self.log = None

    def finish(self):
        self.stop()
        self.client.close()
        (self.directory / "evidence.json").write_text(
            json.dumps(
                {
                    "test_name": self.test_name,
                    "instances": self.instances,
                    "identity": self.last_identity,
                    "observed_runs": self.observed_runs,
                    "observed_states": self.observed_states,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def get(self, path):
        response = self.client.get(path)
        response.raise_for_status()
        return response.json()

    def post(self, path, body):
        response = self.client.post(path, json=body)
        response.raise_for_status()
        return response.json()

    def publish(self, revision, nodes):
        return self.post("/m0/revisions", {"revision_id": revision, "nodes": nodes})

    def submission(
        self, revision, topic=TOPIC, *, thread=None, research=None, previous=None
    ):
        if thread is None:
            thread = str(uuid4())
            self.post("/threads", {"thread_id": thread})
            response = self.client.put(
                f"/m0/bindings/{thread}", json={"revision_id": revision}
            )
            response.raise_for_status()
        turn = str(uuid4())
        body = {
            "research_id": research or str(uuid4()),
            "text": topic,
            "expected_turn_id": previous,
        }
        return {
            "thread": thread,
            "turn": turn,
            "path": f"/atlas/threads/{thread}/submissions/{turn}",
            "body": body,
        }

    def completed(self, submission):
        deadline = time.monotonic() + 30
        last = None
        while time.monotonic() < deadline:
            last = self.get(submission["path"])
            if last["status"] == "completed":
                return last
            if last["status"] in ("blocked", "rejected", "interrupted"):
                raise AssertionError(last)
            time.sleep(0.1)
        raise AssertionError({"last": last, "directory": str(self.directory)})

    def state(self, submission):
        state = self.get(f"/threads/{submission['thread']}/state")
        values = state["values"]
        self.observed_states[submission["thread"]] = {
            "revision_id": values.get("workflow_revision_id"),
            "status": values.get("research_status"),
            "phase": values.get("research_phase"),
            "checkpoint": state["checkpoint"],
            "next": state["next"],
            "report_present": bool(values.get("final_report")),
            "notes": len(values.get("notes", [])),
            "sources": len(values.get("sources", [])),
        }
        return state

    def runs(self, submission):
        runs = self.get(f"/threads/{submission['thread']}/runs?limit=100")
        self.observed_runs[submission["thread"]] = [
            {key: run[key] for key in ("run_id", "status")} for run in runs
        ]
        return runs

    def audit(self, submission, kind):
        return [
            r
            for r in self.get("/m0/identity")["audit"]
            if r["thread_id"] == submission["thread"] and r["kind"] == kind
        ]

    def counts(self, submission):
        return Counter(r["name"] for r in self.audit(submission, "call"))

    def pause(self, point):
        (self.directory / f"pause-{point}").write_text("pause", encoding="utf-8")

    def release(self, point):
        (self.directory / f"release-{point}").write_text("release", encoding="utf-8")

    def entered(self, point):
        marker = self.directory / f"entered-{point}"
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if (
                marker.exists()
                and marker.read_text(encoding="utf-8") == self.instances[-1]
            ):
                return
            time.sleep(0.05)
        raise AssertionError(f"Did not enter {point}: {self.directory}")


@pytest.fixture
def native(request):
    fixture = NativeFixture(request.node.name)
    try:
        fixture.start()
        yield fixture
    finally:
        fixture.finish()


def assert_report(fixture, submission, revision):
    values = fixture.state(submission)["values"]
    assert values["research_status"] == "succeeded", values.get("research_errors")
    assert values["research_phase"] == "complete"
    assert values["workflow_revision_id"] == revision
    assert values["report_research_id"] == submission["body"]["research_id"]
    assert values["active_turn_id"] == submission["turn"]
    assert "API 测试替身" in values["final_report"]
    assert values["notes"] and values["sources"]
    return values


def test_native_revisions_clarification_history_and_concurrent_runs(native):
    f = native
    f.publish("v1", CORE)
    waiting = f.submission("v1", "比较两种构建")
    f.post(waiting["path"], waiting["body"])
    waiting_receipt = f.completed(waiting)
    waiting_state = f.state(waiting)
    assert waiting_state["values"]["research_status"] == "awaiting_input"
    assert [r["name"] for r in f.audit(waiting, "node")] == list(CORE[:2])

    f.publish("v2", EXTENDED)
    conflict = f.client.put(
        f"/m0/bindings/{waiting['thread']}", json={"revision_id": "v2"}
    )
    assert (
        conflict.status_code == 409
        and conflict.json()["error"] == "thread_revision_conflict"
    )
    v2 = f.submission("v2")
    answer = f.submission(
        "v1",
        thread=waiting["thread"],
        research=waiting["body"]["research_id"],
        previous=waiting["turn"],
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        for result in executor.map(
            lambda s: f.post(s["path"], s["body"]), (v2, answer)
        ):
            assert result["run_id"]
    f.completed(v2)
    f.completed(answer)
    old = assert_report(f, answer, "v1")
    new = assert_report(f, v2, "v2")
    assert "[M0 optimized]" not in old["research_brief"]
    assert "[M0 optimized]" in new["research_brief"]
    assert new["raw_notes"] == old["raw_notes"] and new["sources"] == old["sources"]
    assert all("[M0 organized]" in note for note in new["notes"])
    assert len(new["notes"]) == len(old["notes"]) == 1
    assert [r["name"] for r in f.audit(v2, "node")] == list(EXTENDED)
    assert [r["name"] for r in f.audit(answer, "node")] == [*CORE[:2], *CORE]
    assert f.counts(v2)["search"] == f.counts(answer)["search"] == 1
    assert f.counts(answer)["optimize_plan"] == 0
    assert f.counts(v2)["optimize_plan"] == f.counts(v2)["organize_notes"] == 1
    assert all(
        r["detail"]["received_optimized"]
        for r in f.audit(v2, "call")
        if r["name"] == "supervisor"
    )

    before = f.counts(answer)
    history = f.post(f"/threads/{answer['thread']}/history", {"limit": 100})
    assert any(
        s["checkpoint"]["checkpoint_id"] == waiting_state["checkpoint"]["checkpoint_id"]
        for s in history
    )
    historical = f.post(
        f"/threads/{answer['thread']}/state/checkpoint",
        {"checkpoint": waiting_state["checkpoint"]},
    )
    assert historical["values"]["workflow_revision_id"] == "v1"
    assert historical["values"]["research_status"] == "awaiting_input"
    assert f.get(waiting["path"])["checkpoint_id"] == waiting_receipt["checkpoint_id"]
    for _ in range(3):
        f.state(answer)
    assert (
        f.counts(answer) == before and len(f.runs(answer)) == 2 and len(f.runs(v2)) == 1
    )
    reads = [r for r in f.audit(answer, "factory") if r["name"] == "threads.read"]
    assert reads and all(
        not r["detail"]["explicit_revision"] and r["revision_id"] == "v1" for r in reads
    )


def test_native_clarification_can_be_removed(native):
    f = native
    nodes = tuple(n for n in CORE if n != "clarify_with_user")
    f.publish("skip-clarify", nodes)
    s = f.submission("skip-clarify", "比较两种构建")
    f.post(s["path"], s["body"])
    f.completed(s)
    state = assert_report(f, s, "skip-clarify")
    assert f.counts(s)["clarify"] == 0
    assert state["user_requirements"] == "比较两种构建"
    assert [r["name"] for r in f.audit(s, "node")] == list(nodes)


@pytest.mark.parametrize(
    "point,node",
    [
        ("clarify", "clarify_with_user"),
        ("brief", "write_research_brief"),
        ("writer", "final_report_generation"),
    ],
)
def test_native_exact_checkpoint_and_null_input_restore_original_revision(
    native, point, node
):
    f = native
    f.publish("v2", EXTENDED)
    s = f.submission("v2")
    f.pause(point)
    f.post(s["path"], s["body"])
    f.entered(point)
    checkpoint = f.state(s)
    assert checkpoint["next"] == [node]
    before = f.counts(s)
    f.stop()
    f.start()
    # Publish another shape after restart; old revisions must still be resolved.
    f.publish("new-default-shape", CORE)
    restored = f.post(
        f"/threads/{s['thread']}/state/checkpoint",
        {"checkpoint": checkpoint["checkpoint"]},
    )
    assert restored["values"] == checkpoint["values"]
    receipt = f.get(s["path"])
    assert receipt["status"] == "interrupted" and receipt["recovery"]["allowed"]
    assert (
        receipt["recovery"]["checkpoint_id"]
        == checkpoint["checkpoint"]["checkpoint_id"]
    )
    assert len(f.runs(s)) == 1 and f.counts(s) == before
    f.release(point)
    path = s["path"] + "/recoveries/" + str(uuid4())
    body = {
        "research_id": s["body"]["research_id"],
        "parent_run_id": receipt["run_id"],
        "checkpoint_id": receipt["recovery"]["checkpoint_id"],
    }
    f.post(path, body)
    final = f.completed(s)
    assert_report(f, s, "v2")
    assert final["configuration"] == receipt["configuration"]
    assert final["run_id"] != receipt["run_id"] and len(final["attempts"]) == 2
    counts = f.counts(s)
    assert counts["search"] == counts["compression"] == 1
    assert counts["optimize_plan"] == counts["organize_notes"] == 1
    for name in ("clarify", "brief", "writer"):
        assert counts[name] == (2 if name == point else 1)
    resumed = [r for r in f.audit(s, "dispatch") if r["run_id"] == final["run_id"]]
    assert len(resumed) == 1 and resumed[0]["detail"]["input_is_null"]
    assert resumed[0]["detail"]["checkpoint_id"] == body["checkpoint_id"]
    assert not resumed[0]["detail"]["explicit_revision"]
    assert f.post(path, body)["run_id"] == final["run_id"]
    assert f.post(s["path"], s["body"])["run_id"] == final["run_id"]
    assert (
        f.client.post(s["path"] + "/recoveries/" + str(uuid4()), json=body).status_code
        == 409
    )
    assert len(f.runs(s)) == 2 and f.counts(s) == counts
    if point == "writer":
        assert final["event_run_id"] == receipt["event_run_id"]


def test_native_unsafe_research_checkpoint_is_not_resumed(native):
    f = native
    f.publish("v2", EXTENDED)
    s = f.submission("v2")
    f.pause("search")
    f.post(s["path"], s["body"])
    f.entered("search")
    checkpoint = f.state(s)
    f.stop()
    f.start()
    receipt = f.get(s["path"])
    assert receipt["recovery"] == {
        "allowed": False,
        "reason": "research_node_not_resumable",
    }
    before = f.counts(s)
    response = f.client.post(
        s["path"] + "/recoveries/" + str(uuid4()),
        json={
            "research_id": s["body"]["research_id"],
            "parent_run_id": receipt["run_id"],
            "checkpoint_id": checkpoint["checkpoint"]["checkpoint_id"],
        },
    )
    assert response.status_code == 409
    assert f.post(s["path"], s["body"])["status"] == "interrupted"
    assert len(f.runs(s)) == 1 and f.counts(s) == before
    assert before["search"] == 1 and before["writer"] == 0


def test_native_missing_or_incompatible_revision_cannot_use_cached_graph(native):
    f = native
    f.publish("v1", CORE)
    f.publish("v2", EXTENDED)
    s = f.submission("v1")
    f.post(s["path"], s["body"])
    f.completed(s)
    before = f.counts(s)
    store = RevisionStore(f.directory / "workflows.sqlite3")
    with store.connect() as db:
        saved = dict(
            db.execute("SELECT * FROM revisions WHERE revision_id='v1'").fetchone()
        )
    for fault in ("missing", "incompatible", "hash"):
        with store.connect() as db:
            if fault == "missing":
                db.execute("DELETE FROM revisions WHERE revision_id='v1'")
            elif fault == "incompatible":
                definition = json.loads(saved["definition"])
                definition["compiler"] = "removed-implementation"
                db.execute(
                    "UPDATE revisions SET definition=? WHERE revision_id='v1'",
                    (json.dumps(definition),),
                )
            else:
                db.execute(
                    "UPDATE revisions SET content_hash='corrupt' WHERE revision_id='v1'"
                )
        response = f.client.get(f"/threads/{s['thread']}/state")
        assert response.status_code == 409
        assert f.get(s["path"])["status"] == "blocked"
        assert len(f.runs(s)) == 1
        # Restore only this deliberate fault in this test's own database.
        with store.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO revisions VALUES (?, ?, ?)",
                tuple(saved.values()),
            )
    assert f.counts(s) == before
    assert_report(f, s, "v1")


def test_native_unbound_execution_fails_without_model_calls(native):
    f = native
    thread = str(uuid4())
    f.post("/threads", {"thread_id": thread})
    response = f.client.put(f"/m0/bindings/{thread}", json={"revision_id": "unknown"})
    assert response.status_code == 409
    run = f.post(
        f"/threads/{thread}/runs",
        {
            "assistant_id": "research_workflow",
            "input": {"messages": [{"role": "user", "content": TOPIC}]},
        },
    )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        state = f.get(f"/threads/{thread}/runs/{run['run_id']}")
        if state["status"] not in ("pending", "running"):
            break
        time.sleep(0.1)
    assert state["status"] == "error"
    assert not [r for r in f.get("/m0/identity")["audit"] if r["kind"] == "call"]
