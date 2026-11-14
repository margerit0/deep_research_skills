"""Exercise production workflow management, acceptance and factory with real nodes."""

import asyncio
import json
import os
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import AIMessage
from langgraph.config import get_config
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from deep_research import (
    model_config,
    run_configuration,
    structured_output_fallback,
    submission_api,
    workflow_runtime,
)
from deep_research.atlas_api import app as atlas_app
from deep_research.atlas_runtime import compatible_runtime, submissions_enabled
from deep_research.event_journal import INSTANCE_ID
from deep_research.submission_journal import SubmissionJournal

# The launcher establishes an offline fixture environment before graph import.
from tests import atlas_fixture_graph as fixture

directory = Path(os.environ["ATLAS_WORKFLOW_FIXTURE_DIR"])
with sqlite3.connect(directory / "audit.sqlite3") as db:
    db.execute(
        "CREATE TABLE IF NOT EXISTS audit(sequence INTEGER PRIMARY KEY, kind TEXT, name TEXT, thread_id TEXT, run_id TEXT, detail TEXT)"
    )


def record(kind, name, config=None, **details):
    config = config or get_config()
    snapshot = run_configuration._active.get()
    if snapshot:
        details["selection"] = snapshot["selection"]
        details["skill_revisions"] = snapshot["skill_revisions"]
    with sqlite3.connect(directory / "audit.sqlite3", timeout=10) as db:
        db.execute(
            "INSERT INTO audit(kind,name,thread_id,run_id,detail) VALUES (?, ?, ?, ?, ?)",
            (
                kind,
                name,
                str(config.get("configurable", {}).get("thread_id", "")),
                str(config.get("configurable", {}).get("run_id", "")),
                json.dumps(details, ensure_ascii=False),
            ),
        )


def waiting(point):
    if (directory / f"pause-{point}").exists() and not (
        directory / f"release-{point}"
    ).exists():
        (directory / f"entered-{point}").write_text(INSTANCE_ID, encoding="utf-8")
        return True
    return False


def pause(point):
    deadline = time.monotonic() + 90
    while waiting(point):
        if time.monotonic() > deadline:
            raise TimeoutError("Fixture pause expired")
        time.sleep(0.03)


async def apause(point):
    deadline = time.monotonic() + 90
    while waiting(point):
        if time.monotonic() > deadline:
            raise TimeoutError("Fixture pause expired")
        await asyncio.sleep(0.03)


def structured(model, schema, prompt):
    optimizing = prompt.startswith("优化已有研究简报")
    point = (
        "optimize_plan"
        if optimizing
        else "brief"
        if schema is fixture.scope.ResearchQuestion
        else "clarify"
    )
    record("call", point)
    pause(point)
    if optimizing:
        return schema(research_brief="[M3 optimized] Python 3.13 research plan")
    return fixture.structured(model, schema, prompt)


async def plan(messages):
    record(
        "call",
        "supervisor",
        received_optimized=any("[M3 optimized]" in str(m.content) for m in messages),
    )
    return await fixture.plan(messages)


def research(messages):
    record("call", "researcher")
    return fixture.research(messages)


original_search = fixture.researcher.tools_by_name["tavily_search"].invoke


def search(args):
    record("call", "search")
    pause("search")
    return original_search(args)


def compress(messages):
    organizing = "整理现有研究材料" in str(messages[0].content)
    point = "organize_notes" if organizing else "compression"
    record("call", point)
    pause(point)
    return AIMessage(
        content="[M3 organized] Valid original findings [1]"
        if organizing
        else fixture.REPORT
    )


async def write(messages):
    record(
        "call",
        "writer",
        received_organized=any("[M3 organized]" in str(m.content) for m in messages),
    )
    await apause("writer")
    return await fixture.write(messages)


class ModelDouble:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def bind_tools(self, _tools):
        return self

    def with_retry(self, **_kwargs):
        return self

    def invoke(self, messages):
        node = get_config().get("metadata", {}).get("langgraph_node", "")
        return (
            compress(messages)
            if node in {"compress_research", "notes_0", "notes_1"}
            else research(messages)
        )

    async def ainvoke(self, messages):
        node = get_config().get("metadata", {}).get("langgraph_node", "")
        return (
            await write(messages)
            if node == "final_report_generation"
            else await plan(messages)
        )


fixture.scope.invoke_with_structured_output_fallback = structured
structured_output_fallback.invoke_with_structured_output_fallback = structured
fixture.supervisor.supervisor_model_with_tools = SimpleNamespace(ainvoke=plan)
fixture.researcher.model_with_tools = SimpleNamespace(invoke=research)
fixture.researcher.compress_model = SimpleNamespace(invoke=compress)
fixture.researcher.tools_by_name["tavily_search"] = SimpleNamespace(invoke=search)
fixture.full.writer_model = SimpleNamespace(ainvoke=write)
model_config.init_chat_model = lambda **kwargs: ModelDouble(**kwargs)

original_reserve = SubmissionJournal.reserve_in_connection


def reserve(db, *args, **kwargs):
    if (directory / "exit-in-transaction").exists():
        os._exit(86)
    return original_reserve(db, *args, **kwargs)


SubmissionJournal.reserve_in_connection = staticmethod(reserve)
original_create = submission_api.create_native


async def create_native(conn, thread_id, payload, headers, run_id):
    record(
        "dispatch",
        "native",
        {"configurable": {"thread_id": thread_id, "run_id": run_id}},
        graph_id=payload["assistant_id"],
        input_is_null=payload["input"] is None,
        checkpoint_id=payload.get("checkpoint_id"),
    )
    if (directory / "exit-after-intent").exists():
        os._exit(87)
    result = await original_create(conn, thread_id, payload, headers, run_id)
    if (directory / "lose-response").exists():
        (directory / "lose-response").unlink()
        raise RuntimeError("Fixture response loss")
    return result


submission_api.create_native = create_native
if (directory / "missing-plan").exists():
    original_implementations = workflow_runtime.implementations
    workflow_runtime.implementations = lambda: {
        key: handler
        for key, handler in original_implementations().items()
        if key != ("optimize_plan", 1)
    }


async def identity(request):
    with sqlite3.connect(directory / "audit.sqlite3") as db:
        db.row_factory = sqlite3.Row
        audit = [
            {**dict(row), "detail": json.loads(row["detail"])}
            for row in db.execute("SELECT * FROM audit ORDER BY sequence")
        ]
    return JSONResponse(
        {
            "fixture_id": os.environ["ATLAS_WORKFLOW_FIXTURE_ID"],
            "instance_id": INSTANCE_ID,
            "pid": os.getpid(),
            "substitutes": True,
            "compatible_runtime": compatible_runtime(),
            "submission_contract": submissions_enabled(),
            "audit": audit,
        }
    )


agent = fixture.agent
app = Starlette(routes=[*atlas_app.routes, Route("/m3/identity", identity)])
