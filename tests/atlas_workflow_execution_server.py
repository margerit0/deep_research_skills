"""Launch production M3 APIs with model/tool substitutes and isolated persistence."""

import argparse
import os
import socket
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--fixture-id", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    parent = (root / ".local/graph-canvas-m3").resolve()
    directory = args.directory.resolve()
    if not directory.is_relative_to(parent) or directory == parent:
        parser.error("directory must be a case under .local/graph-canvas-m3")
    directory.mkdir(parents=True, exist_ok=True)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", args.port))
    for key in list(os.environ):
        if key.startswith(
            (
                "ATLAS_",
                "LANGSMITH_",
                "LANGCHAIN_",
                "LANGGRAPH_",
                "LLM_",
                "OPENAI_",
                "ANTHROPIC_",
                "TAVILY_",
                "SCOPING_",
                "SUPERVISOR_",
                "RESEARCHER_",
                "SUMMARIZATION_",
                "COMPRESSION_",
                "FINAL_REPORT_",
            )
        ) or key in ("AGENT_RPM", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
            os.environ.pop(key)
    revision_file = directory / "configuration-revision"
    environment = {
        "LANGSMITH_TRACING": "false",
        "LANGCHAIN_TRACING_V2": "false",
        "LANGGRAPH_DISABLE_FILE_PERSISTENCE": "false",
        "NO_PROXY": "*",
        "LLM_BASE_URL": "http://127.0.0.1:1/v1",
        "OPENAI_API_KEY": "fixture-not-a-real-key",
        "ATLAS_EVENT_DB": str(directory / "events.sqlite3"),
        "ATLAS_REPORT_EVENT_DB": str(directory / "reports.sqlite3"),
        "ATLAS_SUBMISSION_DB": str(directory / "submissions.sqlite3"),
        "ATLAS_CONFIG_DB": str(directory / "configs.sqlite3"),
        "ATLAS_WORKFLOW_FIXTURE_DIR": str(directory),
        "ATLAS_WORKFLOW_FIXTURE_ID": args.fixture_id,
        "ATLAS_SUBMISSIONS_ENABLED": "true",
        "ATLAS_CONFIG_FIXTURE": "1",
        "ATLAS_CONFIG_FIXTURE_REVISION": revision_file.read_text().strip()
        if revision_file.exists()
        else "v1",
    }
    os.environ.update(environment)
    sys.path[:0] = [str(root), str(root / "src")]
    os.chdir(directory)
    from langgraph_api.cli import run_server

    run_server(
        host="127.0.0.1",
        port=args.port,
        reload=False,
        open_browser=False,
        allow_blocking=True,
        disable_persistence=False,
        graphs={
            "research_workflow": "deep_research.workflow_runtime:graph",
            "research_agent_full": "tests.atlas_workflow_execution_fixture:agent",
        },
        http={"app": "tests.atlas_workflow_execution_fixture:app"},
        env=environment,
    )


if __name__ == "__main__":
    main()
