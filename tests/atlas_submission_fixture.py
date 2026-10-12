"""Models/tools with durable call counts and externally controlled crash windows."""

import asyncio
import os
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

# This import configures substitutes before importing any model/graph module.
from tests import atlas_fixture_graph as fixture
from deep_research import submission_api
from deep_research.atlas_api import app as atlas_app
from deep_research.atlas_runtime import submissions_enabled
from deep_research.event_journal import INSTANCE_ID

directory = Path(os.environ["ATLAS_SUBMISSION_FIXTURE_DIR"])
audit_path = directory / "calls.sqlite3"
with sqlite3.connect(audit_path) as db:
    db.execute("PRAGMA journal_mode=WAL")
    db.execute(
        "CREATE TABLE IF NOT EXISTS calls (name TEXT NOT NULL, at REAL NOT NULL)"
    )


def count(name):
    with sqlite3.connect(audit_path, timeout=10) as db:
        db.execute("PRAGMA synchronous=FULL")
        db.execute("INSERT INTO calls VALUES (?, ?)", (name, time.time()))


def waiting(point):
    if (directory / f"pause-{point}").exists() and not (
        directory / f"release-{point}"
    ).exists():
        (directory / f"entered-{point}").write_text(INSTANCE_ID, encoding="utf-8")
        return True
    return False


def pause(point):
    deadline = time.monotonic() + 180
    while waiting(point):
        if time.monotonic() > deadline:
            raise TimeoutError("Submission fixture pause expired")
        time.sleep(0.03)


async def apause(point):
    deadline = time.monotonic() + 180
    while waiting(point):
        if time.monotonic() > deadline:
            raise TimeoutError("Submission fixture pause expired")
        await asyncio.sleep(0.03)


original_structured = fixture.scope.invoke_with_structured_output_fallback
original_plan = fixture.supervisor.supervisor_model_with_tools.ainvoke
original_research = fixture.researcher.model_with_tools.invoke
original_search = fixture.researcher.tools_by_name["tavily_search"].invoke
original_compress = fixture.researcher.compress_model.invoke
original_write = fixture.full.writer_model.ainvoke
original_create = submission_api.create_native


def structured(model, schema, prompt):
    point = "brief" if schema is fixture.scope.ResearchQuestion else "clarify"
    count(point)
    pause(point)
    return original_structured(model, schema, prompt)


async def plan(messages):
    count("supervisor")
    return await original_plan(messages)


def research(messages):
    count("researcher")
    return original_research(messages)


def search(args):
    count("search")
    pause("search")
    return original_search(args)


def compress(messages):
    count("compression")
    return original_compress(messages)


async def write(messages):
    count("writer")
    await apause("writer")
    return await original_write(messages)


async def create_native(*args):
    await apause("before-create")
    result = await original_create(*args)
    count("native-created")
    # The durable intent exists, but dispatch acknowledgement and the HTTP
    # response do not. Kill here immediately, without waiting for native flush.
    await apause("after-create")
    return result


async def identity(request):
    with sqlite3.connect(audit_path) as db:
        counts = dict(db.execute("SELECT name, COUNT(*) FROM calls GROUP BY name"))
    return JSONResponse(
        {
            "fixture_id": os.environ["ATLAS_SUBMISSION_FIXTURE_ID"],
            "instance_id": INSTANCE_ID,
            "submission_contract": submissions_enabled(),
            "substitutes": True,
            "calls": counts,
        }
    )


if not getattr(fixture, "_atlas_submission_instrumented", False):
    # The native loader imports the same file separately for graph and HTTP app.
    # Instrument the shared graph objects once so the audit counts actual calls.
    fixture._atlas_submission_instrumented = True
    fixture.scope.invoke_with_structured_output_fallback = structured
    fixture.supervisor.supervisor_model_with_tools = SimpleNamespace(ainvoke=plan)
    fixture.researcher.model_with_tools = SimpleNamespace(invoke=research)
    fixture.researcher.tools_by_name["tavily_search"].invoke = search
    fixture.researcher.compress_model = SimpleNamespace(invoke=compress)
    fixture.full.writer_model = SimpleNamespace(ainvoke=write)
    submission_api.create_native = create_native
    if os.getenv("ATLAS_CONFIG_FIXTURE") == "1":
        from tests.atlas_configuration_fixture import install

        install(fixture, count, structured, plan, research, search, compress, write)
agent = fixture.agent
app = Starlette(routes=[*atlas_app.routes, Route("/atlas-fixture/identity", identity)])
