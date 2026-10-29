import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from deep_research.report_review import (
    ConditionSelection, ReportReviewContext, ReportReviewFormatError,
    ReportReviewRequestError, read_review_json, review_report,
)
from deep_research.review_diagnostics import safe_provider_error


@pytest.mark.parametrize("field,value,location", [
    ("conditions", [{"condition": "ok", "source": {"source_id": 1, "start_line": 1, "end_line": 1}}] * 6, ["conditions"]),
    ("prerequisites_absent_reason", "PRIVATE" * 100, ["prerequisites_absent_reason"]),
    ("conditions", [{"condition": "PRIVATE" * 200, "source": {"source_id": 1, "start_line": 1, "end_line": 1}}], ["conditions", 0, "condition"]),
])
def test_schema_failure_locates_overlong_field_without_saving_input(field, value, location):
    payload = {"prerequisites": [], "prerequisites_absent_reason": "none", "conditions": []}
    payload[field] = value
    model = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content=json.dumps(payload))))
    with pytest.raises(ReportReviewFormatError) as caught:
        asyncio.run(read_review_json(model, ConditionSelection, "prompt", "input", ReportReviewContext()))
    diagnostics = caught.value.diagnostics
    assert diagnostics["validation_errors"][0]["location"] == location
    assert diagnostics["validation_error_types"] == ["too_long" if isinstance(value, list) and len(value) > 5 else "string_too_long"]
    assert "PRIVATE" not in json.dumps(diagnostics)


def test_unknown_field_names_and_error_codes_are_not_diagnostics():
    raw = json.dumps({"passed": True, "issues": [], **{f"PRIVATE_KEY_{i}": "secret" for i in range(20)}})
    model = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content=raw)))
    with pytest.raises(ReportReviewFormatError) as caught:
        asyncio.run(review_report(model, {}, "candidate"))
    diagnostics = caught.value.diagnostics
    assert diagnostics["validation_error_count"] == 20
    assert len(diagnostics["validation_errors"]) == 16
    assert diagnostics["validation_errors_truncated"] is True
    assert "PRIVATE" not in json.dumps(diagnostics)
    assert safe_provider_error({"type": "secret", "code": "secret", "message": "secret"}) == {"type": "unknown", "code": "unknown"}
    assert safe_provider_error({"type": [], "code": {}}) == {"type": "unknown", "code": "unknown"}


def test_http_200_stream_error_is_unavailable_and_keeps_only_safe_sdk_metadata(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    calls = []
    def handler(request):
        calls.append(request)
        data = {"error": {"message": "PRIVATE_RESPONSE", "type": "server_error", "code": "internal_server_error"}}
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, text="data: " + json.dumps(data) + "\n\n")
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            model = ChatOpenAI(model="test", api_key="test", base_url="https://test.invalid/v1", http_async_client=client, max_retries=0)
            return await review_report(model, {}, "candidate")
    with pytest.raises(ReportReviewRequestError) as caught:
        asyncio.run(run())
    assert len(calls) == 1
    diagnostic = caught.value.diagnostics
    assert diagnostic["decision_available"] is False
    assert diagnostic["elapsed_seconds"] >= 0
    assert diagnostic["provider_error"] == {"type": "server_error", "code": "internal_server_error"}
    assert "PRIVATE" not in json.dumps(diagnostic) + str(caught.value)
