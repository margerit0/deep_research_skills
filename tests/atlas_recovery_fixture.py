"""Native API crash fixture, used only in an isolated temporary working directory."""

import os
import time
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

# This import sets substitute credentials before it imports any graph modules.
from tests import atlas_fixture_graph as fixture
from deep_research.atlas_api import app as atlas_app
from deep_research.event_journal import INSTANCE_ID


control_dir = Path(os.environ["ATLAS_RECOVERY_FIXTURE_DIR"])
original_search = fixture.researcher.tools_by_name["tavily_search"].invoke


def paused_search(args):
    """Wait inside the real research subgraph, after its tool_started event."""
    (control_dir / "search-entered").write_text("fixture", encoding="utf-8")
    deadline = time.monotonic() + 180
    while not (control_dir / "release-search").exists():
        if time.monotonic() > deadline:
            raise TimeoutError("Recovery fixture timed out")
        time.sleep(0.05)
    return original_search(args)


async def identity(request):
    return JSONResponse(
        {
            "fixture_id": os.environ["ATLAS_RECOVERY_FIXTURE_ID"],
            "instance_id": INSTANCE_ID,
        }
    )


fixture.researcher.tools_by_name["tavily_search"].invoke = paused_search
agent = fixture.agent
app = Starlette(routes=[*atlas_app.routes, Route("/atlas-fixture/identity", identity)])
