"""Real research nodes under a revision factory, with isolated model/tool substitutes."""

import asyncio
import os
import time
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import HumanMessage
from langgraph.config import get_config
from langgraph.types import Overwrite
from langgraph_sdk.runtime import ServerRuntime
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.routing import Route

# The launcher clears external configuration first. This module then substitutes
# every model/search boundary before the graph can execute.
from tests import atlas_fixture_graph as fixture
from tests.atlas_workflow_factory import (
    CORE,
    GRAPH_ID,
    Revision,
    RevisionError,
    RevisionStore,
    compile_revision,
)

# isort: split

from deep_research import submission_api
from deep_research.atlas_api import app as atlas_app
from deep_research.atlas_runtime import compatible_runtime, submissions_enabled
from deep_research.event_journal import INSTANCE_ID
from deep_research.state_scope import AgentInputState, AgentState
from deep_research.submission_journal import guard_execution

directory = Path(os.environ["ATLAS_WORKFLOW_FIXTURE_DIR"])
store = RevisionStore(directory / "workflows.sqlite3")


class WorkflowState(AgentState):
    workflow_revision_id: str
    workflow_content_hash: str


def count(name, **detail):
    config = get_config()
    revision = store.resolve(str(config["configurable"]["thread_id"]))
    store.record("call", name, config, revision.revision_id, **detail)


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
            raise TimeoutError("M0 fixture pause expired")
        time.sleep(0.03)


async def apause(point):
    deadline = time.monotonic() + 90
    while waiting(point):
        if time.monotonic() > deadline:
            raise TimeoutError("M0 fixture pause expired")
        await asyncio.sleep(0.03)


original_structured = fixture.structured
original_plan = fixture.plan
original_research = fixture.research
original_search = fixture.researcher.tools_by_name["tavily_search"].invoke
original_compress = fixture.researcher.compress_model.invoke
original_write = fixture.write
original_create = submission_api.create_native


def structured(model, schema, prompt):
    point = "brief" if schema is fixture.scope.ResearchQuestion else "clarify"
    count(point)
    pause(point)
    return original_structured(model, schema, prompt)


async def plan(messages):
    count(
        "supervisor",
        received_optimized=any("[M0 optimized]" in str(m.content) for m in messages),
    )
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


def optimize_plan(state):
    guard_execution(state, "optimize_plan")
    count("optimize_plan")
    brief = state["research_brief"] + "\n[M0 optimized]"
    return {
        "research_brief": brief,
        "supervisor_messages": Overwrite([HumanMessage(content=brief)]),
    }


def organize_notes(state):
    guard_execution(state, "organize_notes")
    count("organize_notes")
    return {"notes": Overwrite(["[M0 organized]\n" + note for note in state["notes"]])}


async def entered(name, state, config, revision):
    # Check the durable archive again even when the compiled graph was cached.
    store.resolve(str(config["configurable"]["thread_id"]), revision.revision_id)
    store.record("node", name, config, revision.revision_id)


@lru_cache(maxsize=32)
def compiled(revision):
    handlers = {name: getattr(fixture.full, name) for name in CORE}
    handlers.update(optimize_plan=optimize_plan, organize_notes=organize_notes)
    return compile_revision(revision, handlers, WorkflowState, AgentInputState, entered)


def graph(config, runtime: ServerRuntime):
    configurable = config.get("configurable", {})
    thread_id = configurable.get("thread_id")
    if not thread_id and runtime.access_context == "assistants.read":
        # Schema/graph inspection has no execution identity and creates no binding.
        return compiled(Revision("schema-only", CORE))
    try:
        revision = store.resolve(
            str(thread_id or ""), configurable.get("workflow_revision_id")
        )
    except RevisionError as exc:
        raise HTTPException(409, str(exc)) from exc
    store.record(
        "factory",
        runtime.access_context,
        config,
        revision.revision_id,
        explicit_revision="workflow_revision_id" in configurable,
        checkpoint_id=configurable.get("checkpoint_id"),
    )
    return compiled(revision)


async def create_native(conn, thread_id, payload, headers, run_id):
    # M0 seam only: keep the real journal, run identity, config and recovery rules.
    # Production will bind workflow + acceptance atomically in M1/M3.
    try:
        revision = store.resolve(str(thread_id))
    except RevisionError as exc:
        raise HTTPException(409, str(exc)) from exc
    payload = {**payload, "assistant_id": GRAPH_ID}
    store.record(
        "dispatch",
        "native",
        {"configurable": {"thread_id": thread_id, "run_id": run_id}},
        revision.revision_id,
        input_is_null=payload.get("input") is None,
        checkpoint_id=payload.get("checkpoint_id"),
        explicit_revision="workflow_revision_id"
        in payload.get("config", {}).get("configurable", {}),
    )
    return await original_create(conn, thread_id, payload, headers, run_id)


async def identity(request):
    return JSONResponse(
        {
            "fixture_id": os.environ["ATLAS_WORKFLOW_FIXTURE_ID"],
            "instance_id": INSTANCE_ID,
            "pid": os.getpid(),
            "substitutes": True,
            "compatible_runtime": compatible_runtime(),
            "submission_contract": submissions_enabled(),
            "audit": store.audit(),
        }
    )


async def publish(request):
    body = await request.json()
    try:
        revision = Revision(
            body["revision_id"],
            tuple(body["nodes"]),
            body.get("compiler", "m0-command-adapter-v1"),
        )
        store.publish(revision)
        return JSONResponse(
            {"revision_id": revision.revision_id, "content_hash": revision.content_hash}
        )
    except (KeyError, TypeError, RevisionError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)


async def bind(request):
    body = await request.json()
    try:
        revision = store.bind(request.path_params["thread_id"], body["revision_id"])
        return JSONResponse(
            {"revision_id": revision.revision_id, "content_hash": revision.content_hash}
        )
    except (KeyError, RevisionError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)


fixture.scope.invoke_with_structured_output_fallback = structured
fixture.supervisor.supervisor_model_with_tools = SimpleNamespace(ainvoke=plan)
fixture.researcher.model_with_tools = SimpleNamespace(invoke=research)
fixture.researcher.tools_by_name["tavily_search"] = SimpleNamespace(invoke=search)
fixture.researcher.compress_model = SimpleNamespace(invoke=compress)
fixture.full.writer_model = SimpleNamespace(ainvoke=write)
submission_api.create_native = create_native
app = Starlette(
    routes=[
        *atlas_app.routes,
        Route("/m0/identity", identity),
        Route("/m0/revisions", publish, methods=["POST"]),
        Route("/m0/bindings/{thread_id}", bind, methods=["PUT"]),
    ]
)
