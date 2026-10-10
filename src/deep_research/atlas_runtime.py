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


def flush_native(*, checkpoints: bool = False) -> None:
    """Persist native identities before dispatch and parent checkpoints before calls.

    All mutations still go through LangGraph. The normal ten-second flush uses the
    same serialized writer; checkpoint blobs/writes precede their checkpoint index.
    Recovery additionally validates identity, next node, and recorded state digest.
    """
    if not submissions_enabled():
        raise RuntimeError("Unsupported Atlas execution runtime")
    from langgraph_runtime_inmem import _persistence, checkpoint, database

    if _persistence.DISABLE_FILE_PERSISTENCE or checkpoint.DISABLE_FILE_PERSISTENCE:
        raise RuntimeError("Native persistence is disabled")
    stores = [database.GLOBAL_STORE, database.GLOBAL_RETRY_COUNTER._counters]
    if checkpoints:
        saver = checkpoint.Checkpointer()
        stores = [saver.blobs, saver.writes, saver.storage, *stores]
    with _PERSIST_LOCK:
        for ref in list(_persistence._stores.values()):
            store = ref()
            if store is not None and not getattr(store, "_atlas_sync", False):
                store.sync = partial(_sync, store)
                store._atlas_sync = True
        for store in stores:
            store.sync()


def native_modules():
    """Import only inside native HTTP requests, never during standalone evaluation."""
    if not submissions_enabled():
        raise RuntimeError("Unsupported Atlas execution runtime")
    from langgraph_api.models.run import create_valid_run
    from langgraph_runtime_inmem.database import connect
    from langgraph_runtime_inmem.ops import RUN_LOCK, Runs, Threads

    return connect, RUN_LOCK, Runs, Threads, create_valid_run
