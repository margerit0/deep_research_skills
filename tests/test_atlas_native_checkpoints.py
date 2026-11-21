"""Regressions for the version-gated native checkpoint read and durability adapters."""

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import PersistentDict
from langgraph.checkpoint.serde.jsonplus import (
    JsonPlusSerializer,
    _msgpack_ext_hook_to_json,
)
from langgraph.types import Overwrite

from deep_research import atlas_runtime, submission_api


@dataclass
class OtherValue:
    value: str


def test_read_serializer_preserves_only_checkpoint_overwrite():
    writer = JsonPlusSerializer()
    reader = JsonPlusSerializer(
        __unpack_ext_hook__=atlas_runtime._preserve_checkpoint_overwrite(
            _msgpack_ext_hook_to_json
        )
    )

    def read(value):
        return reader.loads_typed(writer.dumps_typed(value))

    assert read(Overwrite(["replacement"])) == Overwrite(["replacement"])
    assert (
        read(Overwrite([HumanMessage(content="keep the JSON view")])).value[0][
            "content"
        ]
        == "keep the JSON view"
    )
    assert read(OtherValue("unchanged")) == {"value": "unchanged"}
    assert read({"value": "not an instruction"}) == {"value": "not an instruction"}


def test_read_view_does_not_replace_primary_persistence_stores(tmp_path):
    names = ("storage", "writes", "blobs")
    stores = {name: PersistentDict(filename=str(tmp_path / name)) for name in names}
    saver = SimpleNamespace(**stores)
    checkpoint = SimpleNamespace(MEMORY=saver, Checkpointer=lambda: saver)
    ops = SimpleNamespace(_msgpack_ext_hook_to_json=_msgpack_ext_hook_to_json)
    registered = {}

    def register(store):
        registered[store.filename] = store

    atlas_runtime._bind_checkpoints(checkpoint, register, ops)
    adapter = ops._msgpack_ext_hook_to_json
    assert atlas_runtime._bind_checkpoints(checkpoint, register, ops) is saver
    assert ops._msgpack_ext_hook_to_json is adapter
    for primary in stores.values():
        primary["primary"] = 1
        primary.sync()
        temporary = PersistentDict(filename=primary.filename)
        checkpoint.register_persistent_dict(temporary)
        temporary.load()
        assert not temporary
        temporary["transient"] = 2
        temporary.sync()
        assert registered[primary.filename] is primary
        reopened = PersistentDict(filename=primary.filename)
        reopened.load()
        assert dict(reopened) == {"primary": 1}


def test_receipt_does_not_seal_terminal_pending_writes(monkeypatch):
    attempt = {
        "attempt_id": "turn",
        "run_id": "run",
        "kind": "submit",
        "checkpoint_node": None,
        "completed_checkpoint": None,
        "owner_id": submission_api.INSTANCE_ID,
        "rejected": False,
    }
    record = {
        "thread_id": "thread",
        "research_id": "research",
        "turn_id": "turn",
        "attempts": [attempt],
    }
    run = {
        "thread_id": "thread",
        "run_id": "run",
        "status": "running",
        "metadata": {"atlas_turn_id": "turn", "atlas_research_id": "research"},
    }
    conn = SimpleNamespace(store={"threads": [{"thread_id": "thread"}], "runs": [run]})
    reads, persisted = [], []
    committed = False

    async def read(_conn, thread_id, checkpoint_id):
        assert thread_id == "thread"
        reads.append(checkpoint_id)
        exact = "terminal" if committed else "staged"
        assert checkpoint_id is None or checkpoint_id == exact
        terminal = committed or checkpoint_id is None
        return SimpleNamespace(
            values={
                "active_research_id": "research",
                "active_turn_id": "turn",
                "research_status": "succeeded" if terminal else "running",
            },
            next=() if terminal else ("final_report_generation",),
            config={"configurable": {"checkpoint_id": exact}},
            metadata={"run_id": "run"},
        )

    def flush(*, checkpoints):
        persisted.append(("flush", checkpoints))

    def confirm(run_id, checkpoint_id):
        persisted.append((run_id, checkpoint_id))
        attempt["completed_checkpoint"] = checkpoint_id

    monkeypatch.setattr(submission_api, "read_snapshot", read)
    monkeypatch.setattr(submission_api, "flush_native", flush)
    monkeypatch.setattr(
        submission_api,
        "get_submission_journal",
        lambda: SimpleNamespace(confirm_completed=confirm),
    )

    assert asyncio.run(submission_api.receipt(conn, record))["status"] == "accepted"
    assert reads == [None, "staged"] and not persisted
    committed = True
    receipt = asyncio.run(submission_api.receipt(conn, record))
    assert receipt["status"] == "completed" and receipt["checkpoint_id"] == "terminal"
    assert reads[-2:] == [None, "terminal"]
    assert persisted == [("flush", True), ("run", "terminal")]
    assert asyncio.run(submission_api.receipt(conn, record)) == receipt
    assert reads[-2:] == ["terminal", "terminal"]
    assert len(persisted) == 2
