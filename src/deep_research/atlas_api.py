"""Read-only Atlas capabilities, mounted alongside the native LangGraph API.

LangGraph loads the root .env before importing apps/graphs. Standalone scripts
must do the same before importing graph modules.
"""

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from deep_research.model_config import MODEL_ROLES, public_model_config


async def config(request):
    """Expose the running process's model identities and supported controls."""
    payload = public_model_config()
    if len(payload["models"]) != len(MODEL_ROLES):
        return JSONResponse(
            {"detail": "Research models are not ready."}, status_code=503
        )
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


app = Starlette(routes=[Route("/atlas/config", config, methods=["GET"])])
