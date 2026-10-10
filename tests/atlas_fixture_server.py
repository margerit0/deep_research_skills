"""Start the ordinary native API fixture without touching development state."""

import argparse
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=2025)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--fixture-id", default=str(uuid4()))
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    # The native launcher otherwise silently chooses another port.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", args.port))

    root = Path(__file__).resolve().parents[1]
    parent = root / ".local" / "atlas-api-fixture"
    parent.mkdir(parents=True, exist_ok=True)
    directory = (
        args.directory.resolve()
        if args.directory
        else Path(tempfile.mkdtemp(prefix="case-", dir=parent))
    )
    if not directory.is_relative_to(parent.resolve()) or directory == parent.resolve():
        parser.error(
            "directory must be a case directory under .local/atlas-api-fixture"
        )
    directory.mkdir(parents=True, exist_ok=True)
    config = json.loads(
        (root / "tests/atlas-langgraph.json").read_text(encoding="utf-8")
    )
    os.environ.update(config["env"])
    os.environ["ATLAS_API_FIXTURE_ID"] = args.fixture_id
    os.environ.pop("ATLAS_EVENT_DB", None)
    sys.path[:0] = [str(root), str(root / "src")]
    os.chdir(directory)

    # Some persistence modules initialize during this import. Set env first,
    # then explicitly pass the mode: CLI 0.4.26 drops disable_persistence while
    # validating config, and run_server overrides its environment variable.
    from langgraph_api.cli import run_server

    graphs = {}
    for name, spec in config["graphs"].items():
        path, export = spec.rsplit(":", 1)
        graphs[name] = f"{(root / path).resolve().as_posix()}:{export}"
    print(f"Native API fixture directory: {directory}", flush=True)
    run_server(
        host="127.0.0.1",
        port=args.port,
        reload=False,
        open_browser=False,
        allow_blocking=True,
        disable_persistence=True,
        graphs=graphs,
        http={"app": f"{Path(__file__).resolve().as_posix()}:app"},
        env=config["env"],
    )


def fixture_app():
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    from deep_research.atlas_api import app as atlas_app
    from deep_research.event_journal import journal_path
    from langgraph_runtime_inmem import _persistence, checkpoint

    async def identity(request):
        return JSONResponse(
            {
                "fixture_id": os.environ["ATLAS_API_FIXTURE_ID"],
                "file_persistence_disabled": (
                    _persistence.DISABLE_FILE_PERSISTENCE
                    and checkpoint.DISABLE_FILE_PERSISTENCE
                ),
                "event_journal_enabled": journal_path() is not None,
            }
        )

    return Starlette(
        routes=[*atlas_app.routes, Route("/atlas-fixture/identity", identity)]
    )


if __name__ == "__main__":
    main()
else:
    app = fixture_app()
