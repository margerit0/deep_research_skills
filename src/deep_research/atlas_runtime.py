"""Version-gated adapter for the local LangGraph development runtime.

Keep private runtime dependencies here. This is deliberately not a distributed
queue or a replacement for the native run, checkpoint, and streaming APIs.
"""

from __future__ import annotations

import os
import pickle
import tempfile
import threading
from functools import lru_cache, partial
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

_PERSIST_LOCK = threading.RLock()
TESTED_RUNTIME = {
    "langgraph": "1.1.3",
    "langgraph-api": "0.8.7",
    "langgraph-checkpoint": "4.1.0",
    "langgraph-runtime-inmem": "0.28.1",
}


@lru_cache(maxsize=1)
def compatible_runtime() -> bool:
    """Fail closed after dependency changes until native fault tests are rerun."""
    try:
        return all(
            version(package) == expected for package, expected in TESTED_RUNTIME.items()
        )
    except PackageNotFoundError:
        return False


def submissions_enabled() -> bool:
    """Only advertise durable acceptance for the tested persistent local runtime."""
    return (
        compatible_runtime()
        and os.getenv("LANGGRAPH_RUNTIME_VARIANT", "inmem") == "inmem"
        and os.getenv("LANGGRAPH_DISABLE_FILE_PERSISTENCE", "false").lower() != "true"
        and os.getenv("ATLAS_SUBMISSIONS_ENABLED", "true").lower() != "false"
    )


def _sync(store) -> None:
    # Serialize the periodic native flush and our barriers. A unique temporary
    # file also avoids colliding with a flush already in progress at installation.
    with _PERSIST_LOCK:
        if store.flag == "r":
            raise RuntimeError("Native persistence is read-only")
        path = Path(store.filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=path.parent, prefix=path.name + ".atlas-", delete=False
            ) as output:
                temporary = Path(output.name)
                pickle.dump(dict(store), output, protocol=2)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def _install_sync(store):
    if not getattr(store, "_atlas_sync", False):
        store.sync = partial(_sync, store)
        store._atlas_sync = True


def _preserve_checkpoint_overwrite(decode):
    from langgraph.checkpoint.serde.jsonplus import EXT_CONSTRUCTOR_KW_ARGS
    from langgraph.types import Overwrite
    from ormsgpack import OPT_NON_STR_KEYS, unpackb

    def read_extension(code, data):
        # Native State.get and history decode to JSON before applying pending
        # writes. Preserve this one reducer instruction, not arbitrary types.
        if code == EXT_CONSTRUCTOR_KW_ARGS:
            try:
                module, name, kwargs = unpackb(
                    data, ext_hook=decode, option=OPT_NON_STR_KEYS
                )
            except (TypeError, ValueError):
                pass
            else:
                if (
                    (module, name) == ("langgraph.types", "Overwrite")
                    and isinstance(kwargs, dict)
                    and kwargs.keys() == {"value"}
                ):
                    return Overwrite(kwargs["value"])
        return decode(code, data)

    return read_extension


def _bind_checkpoints(checkpoint, register, ops):
    # 0.28.1 constructs three temporary PersistentDicts when selecting a
    # JSON serializer for State.get/history, then immediately swaps in the
    # shared dictionaries. Registering the temporaries replaces the real
    # flush-loop weakrefs. They must neither read nor write these files.
    saver = checkpoint.Checkpointer()
    if getattr(saver, "_atlas_primary_stores", False):
        return saver
    primary = {
        store.filename: store for store in (saver.blobs, saver.writes, saver.storage)
    }

    def register_checkpoint(store):
        owner = primary.get(store.filename)
        if checkpoint.MEMORY is saver and owner is not None and store is not owner:
            store.load = store.sync = lambda: None
        else:
            register(store)

    checkpoint.register_persistent_dict = register_checkpoint
    ops._msgpack_ext_hook_to_json = _preserve_checkpoint_overwrite(
        ops._msgpack_ext_hook_to_json
    )
    for store in primary.values():
        _install_sync(store)
        register(store)
    saver._atlas_primary_stores = True
    return saver


def _native_checkpoints():
    from langgraph_runtime_inmem import _persistence, checkpoint, ops

    if _persistence.DISABLE_FILE_PERSISTENCE or checkpoint.DISABLE_FILE_PERSISTENCE:
        raise RuntimeError("Native persistence is disabled")
    with _PERSIST_LOCK:
        return _bind_checkpoints(checkpoint, _persistence.register_persistent_dict, ops)


def initialize_native_runtime() -> None:
    """Install the version-gated adapters before native HTTP reads start."""
    if submissions_enabled():
        _native_checkpoints()


def flush_native(*, checkpoints: bool = False) -> None:
    """Persist native identities before dispatch and parent checkpoints before calls.

    All mutations still go through LangGraph. The normal ten-second flush uses the
    same serialized writer; checkpoint blobs/writes precede their checkpoint index.
    Recovery additionally validates identity, next node, and recorded state digest.
    """
    if not submissions_enabled():
        raise RuntimeError("Unsupported Atlas execution runtime")
    from langgraph_runtime_inmem import _persistence, database

    with _PERSIST_LOCK:
        saver = _native_checkpoints()
        stores = [database.GLOBAL_STORE, database.GLOBAL_RETRY_COUNTER._counters]
        if checkpoints:
            stores = [saver.blobs, saver.writes, saver.storage, *stores]
        for ref in list(_persistence._stores.values()):
            store = ref()
            if store is not None:
                _install_sync(store)
        for store in stores:
            store.sync()


def native_modules():
    """Import only inside native HTTP requests, never during standalone evaluation."""
    if not submissions_enabled():
        raise RuntimeError("Unsupported Atlas execution runtime")
    from langgraph_api.models.run import create_valid_run
    from langgraph_runtime_inmem.database import connect
    from langgraph_runtime_inmem.ops import RUN_LOCK, Runs, Threads

    _native_checkpoints()
    return connect, RUN_LOCK, Runs, Threads, create_valid_run


def workflow_graph_registered() -> bool:
    """Check the actual server registry before advertising or accepting workflows."""
    if not submissions_enabled():
        return False
    try:
        from langgraph_api.graph import GRAPHS

        from deep_research.workflow_runtime import graph

        return GRAPHS.get("research_workflow") is graph
    except Exception:
        return False
