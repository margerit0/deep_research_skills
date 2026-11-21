"""Deterministic M0 contract and actual scheduler checks, without model imports."""

import asyncio
import json
import operator
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, TypedDict

import pytest
from langgraph.graph import END
from langgraph.types import Command, Overwrite

from tests.atlas_workflow_factory import (
    CORE,
    EXTENDED,
    NORMAL_DESTINATIONS,
    Revision,
    RevisionError,
    RevisionStore,
    compile_revision,
    routed,
)


def test_revision_and_binding_are_immutable_across_reopen(tmp_path):
    path = tmp_path / "workflow.sqlite3"
    store = RevisionStore(path)
    v1 = store.publish(Revision("v1", CORE))
    store.publish(v1)
    store.publish(Revision("v2", EXTENDED))
    with pytest.raises(RevisionError, match="revision_immutable"):
        store.publish(Revision("v1", EXTENDED))
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: store.bind("thread", "v1"), range(8)))
    assert results == [v1] * 8
    assert RevisionStore(path).resolve("thread") == v1
    with pytest.raises(RevisionError, match="thread_revision_conflict"):
        store.bind("thread", "v2")
    with pytest.raises(RevisionError, match="thread_revision_conflict"):
        store.resolve("thread", "v2")


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("missing", "revision_missing"),
        ("incompatible", "revision_incompatible"),
        ("identity", "revision_identity_mismatch"),
        ("hash", "revision_hash_mismatch"),
        ("binding", "binding_hash_mismatch"),
    ],
)
def test_broken_archive_never_falls_back(tmp_path, fault, reason):
    store = RevisionStore(tmp_path / "workflow.sqlite3")
    store.publish(Revision("v1", CORE))
    store.publish(Revision("v2", EXTENDED))
    store.bind("thread", "v1")
    with store.connect() as db:
        if fault == "missing":
            db.execute("DELETE FROM revisions WHERE revision_id='v1'")
        elif fault in ("incompatible", "identity"):
            body = json.loads(
                db.execute(
                    "SELECT definition FROM revisions WHERE revision_id='v1'"
                ).fetchone()[0]
            )
            if fault == "incompatible":
                body["compiler"] = "unavailable-compiler"
            else:
                body["revision_id"] = "wrong-identity"
            db.execute(
                "UPDATE revisions SET definition=? WHERE revision_id='v1'",
                (json.dumps(body),),
            )
        elif fault == "hash":
            db.execute(
                "UPDATE revisions SET content_hash='changed' WHERE revision_id='v1'"
            )
        else:
            db.execute(
                "UPDATE bindings SET content_hash='changed' WHERE thread_id='thread'"
            )
    with pytest.raises(RevisionError, match=reason):
        store.resolve("thread")


def test_unknown_binding_and_topology_are_rejected(tmp_path):
    store = RevisionStore(tmp_path / "workflow.sqlite3")
    with pytest.raises(RevisionError, match="thread_revision_missing"):
        store.resolve("unbound")
    with pytest.raises(RevisionError, match="revision_missing"):
        store.bind("thread", "unknown")
    with pytest.raises(RevisionError, match="revision_invalid"):
        store.publish(Revision("invalid", (*CORE, CORE[0])))


class State(TypedDict, total=False):
    workflow_revision_id: str
    workflow_content_hash: str
    visited: Annotated[list[str], operator.add]
    notes: Annotated[list[str], operator.add]
    research_phase: str


@pytest.mark.parametrize(
    "nodes", [CORE, EXTENDED, tuple(n for n in CORE if n != CORE[1])]
)
def test_actual_execution_follows_only_published_successors(nodes):
    calls = []

    def handler(name):
        def invoke(state):
            calls.append(name)
            update = {"visited": [name]}
            if name == "organize_notes":
                update["notes"] = Overwrite(["organized"])
            elif name == "supervisor_subgraph":
                update["notes"] = Overwrite(["evidence"])
            if name in NORMAL_DESTINATIONS and name != CORE[-1]:
                return Command(update=update, goto=NORMAL_DESTINATIONS[name])
            return update

        return invoke

    revision = Revision("test", nodes)
    graph = compile_revision(revision, {n: handler(n) for n in nodes}, State)
    result = asyncio.run(graph.ainvoke({"notes": ["stale"]}))
    assert calls == list(nodes)
    assert result["visited"] == list(nodes)
    assert result["notes"] == (
        ["organized"] if "organize_notes" in nodes else ["evidence"]
    )
    assert result["workflow_content_hash"] == revision.content_hash


def test_wait_or_failure_end_does_not_follow_normal_edge():
    calls = []

    def prepare(state):
        calls.append("prepare")
        return Command(goto=CORE[1])

    def wait(state):
        calls.append("clarify")
        return Command(goto=END, update={"visited": ["waiting"]})

    def forbidden(state):
        pytest.fail("END must never schedule the normal successor")

    handlers = {n: forbidden for n in CORE}
    handlers.update(prepare_research=prepare, clarify_with_user=wait)
    graph = compile_revision(Revision("v1", CORE), handlers, State)
    result = asyncio.run(graph.ainvoke({}))
    assert result["visited"] == ["waiting"]
    assert calls == ["prepare", "clarify"]


def test_adapter_rejects_unknown_route_and_checkpoint_revision():
    with pytest.raises(RevisionError, match="unsupported_business_route"):
        routed(Command(goto=["a", "b"]), "a", "replacement")
    graph = compile_revision(
        Revision("v1", CORE), {n: lambda state: {} for n in CORE}, State
    )
    with pytest.raises(RevisionError, match="checkpoint_revision_conflict"):
        asyncio.run(graph.ainvoke({"workflow_revision_id": "v2"}))
