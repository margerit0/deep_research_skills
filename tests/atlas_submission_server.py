"""Launch the 1B native fault fixture in an isolated, persistent case directory."""

import argparse
import os
from pathlib import Path
import socket
import sys
import tempfile
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=2027)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--fixture-id", default=str(uuid4()))
    args = parser.parse_args()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", args.port))
    root = Path(__file__).resolve().parents[1]
    parent = root / ".local" / "atlas-submission-api"
    parent.mkdir(parents=True, exist_ok=True)
    directory = (
        args.directory.resolve()
        if args.directory
        else Path(tempfile.mkdtemp(prefix="case-", dir=parent))
    )
    if not directory.is_relative_to(parent.resolve()) or directory == parent.resolve():
        parser.error(
            "directory must be a case directory under .local/atlas-submission-api"
        )
    directory.mkdir(parents=True, exist_ok=True)
    environment = {
        "LANGGRAPH_DISABLE_FILE_PERSISTENCE": "false",
        "LANGSMITH_TRACING": "false",
        "NO_PROXY": "*",
        "ATLAS_SUBMISSIONS_ENABLED": "true",
        "ATLAS_EVENT_DB": str(directory / "events.sqlite3"),
        "ATLAS_SUBMISSION_DB": str(directory / "submissions.sqlite3"),
        "ATLAS_SUBMISSION_FIXTURE_DIR": str(directory),
        "ATLAS_SUBMISSION_FIXTURE_ID": args.fixture_id,
    }
    os.environ.update(environment)
    sys.path[:0] = [str(root), str(root / "src")]
    os.chdir(directory)
    from langgraph_api.cli import run_server

    fixture = (root / "tests/atlas_submission_fixture.py").as_posix()
    print(f"Atlas submission fixture: {directory}", flush=True)
    run_server(
        host="127.0.0.1",
        port=args.port,
        reload=False,
        open_browser=False,
        allow_blocking=True,
        disable_persistence=False,
        graphs={"research_agent_full": f"{fixture}:agent"},
        http={"app": f"{fixture}:app"},
        env=environment,
    )


if __name__ == "__main__":
    main()
