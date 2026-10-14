"""Atlas acceptance, execution recovery and read APIs alongside LangGraph.

LangGraph loads the root .env before importing apps/graphs. Standalone scripts
must do the same before importing graph modules.
"""

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.routing import Route

from deep_research.model_config import MODEL_ROLES, public_model_config
from deep_research.event_journal import EventIdentity, get_event_journal
from deep_research.submission_api import get_receipt, recover, submit
from deep_research.report_streaming import get_report_journal


async def config(request):
    """Expose the running process's model identities and supported controls."""
    payload = public_model_config()
    if len(payload["models"]) != len(MODEL_ROLES):
        return JSONResponse(
            {"detail": "Research models are not ready."}, status_code=503
        )
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


async def events(request):
    """Read a bounded page without touching the native run or its execution."""
    try:
        research_id = request.query_params["research_id"]
        turn_id = request.query_params["turn_id"]
        after = int(request.query_params.get("after", "0"))
        limit = int(request.query_params.get("limit", "50"))
        if not all(0 < len(value) <= 128 for value in (research_id, turn_id)):
            raise ValueError("Invalid identity")
        if not 0 <= after <= 2**53 - 1 or not 1 <= limit <= 100:
            raise ValueError("Invalid page")
    except (KeyError, ValueError):
        return JSONResponse(
            {"detail": "Invalid event replay request."}, status_code=400
        )
    identity = EventIdentity(
        str(request.path_params["thread_id"]),
        str(request.path_params["run_id"]),
        research_id,
        turn_id,
    )
    try:
        journal = (
            get_report_journal()
            if request.url.path.endswith("/report-events")
            else get_event_journal()
        )
        if journal is None:
            return JSONResponse(
                {"detail": "Event replay is disabled."}, status_code=404
            )
        payload = await run_in_threadpool(
            journal.read, identity, after, limit, request.query_params.get("journal_id")
        )
    except ValueError:
        return JSONResponse(
            {"detail": "Event replay is unavailable for this submission."},
            status_code=409,
        )
    except Exception:
        return JSONResponse(
            {"detail": "Event replay is temporarily unavailable."}, status_code=503
        )
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


app = Starlette(
    routes=[
        Route("/atlas/config", config, methods=["GET"]),
        Route(
            "/atlas/threads/{thread_id:uuid}/submissions/{turn_id:uuid}",
            submit,
            methods=["POST"],
        ),
        Route(
            "/atlas/threads/{thread_id:uuid}/submissions/{turn_id:uuid}",
            get_receipt,
            methods=["GET"],
        ),
        Route(
            "/atlas/threads/{thread_id:uuid}/submissions/{turn_id:uuid}/recoveries/{attempt_id:uuid}",
            recover,
            methods=["POST"],
        ),
        Route(
            "/atlas/threads/{thread_id:uuid}/runs/{run_id:uuid}/events",
            events,
            methods=["GET"],
        ),
        Route(
            "/atlas/threads/{thread_id:uuid}/runs/{run_id:uuid}/report-events",
            events,
            methods=["GET"],
        ),
    ]
)
