import asyncio
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import httpx
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from deep_research.report_review import ReportReviewFormatError, review_report, review_record
from deep_research.source_evidence import capture_source_evidence, record_source_evidence


@pytest.mark.parametrize("payload", [
    '{"passed": true, "issues": ["Lost exception"]}',
    '{"passed": false, "issues": []}',
    '{"passed": "true", "issues": []}',
    'Not JSON',
])
def test_invalid_review_never_means_pass(payload):
    model = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content=payload)))
    with pytest.raises(ValueError):
        asyncio.run(review_report(model, {}, "Candidate"))


def test_reviewer_receives_original_source_independent_of_notes():
    with capture_source_evidence() as evidence:
        record_source_evidence("https://example.com/v1", {"raw_content": "In 2020, 10% was a future target. Measured improvement was 3% only in saline water."})
    state = {"source_evidence": evidence, "sources": [{"url": evidence[0]["url"]}],
             "notes": ["UNSUPPORTED_INTERNAL"], "user_requirements": "约 500 字"}
    invoke = AsyncMock(side_effect=[
        AIMessage(content=json.dumps({"prerequisites": [],
            "prerequisites_absent_reason": "This passage gives only measurements and a historical target.",
            "conditions": [{"condition": "The measured gain applies only in saline water.",
            "source": {"source_id": 1, "start_line": 1, "end_line": 1}}]})),
        AIMessage(content='{"passed": false, "issues": ["Target presented as measured."]}'),
    ])
    result = asyncio.run(review_report(SimpleNamespace(ainvoke=invoke), state, "Gain is 10%."))
    prompt = str(invoke.call_args.args[0])
    assert evidence[0]["text"] in prompt and "Gain is 10%." in prompt
    assert "UNSUPPORTED_INTERNAL" not in prompt
    assert result["passed"] is False
    assert review_record("candidate", "attempt", result)["writing_attempt_id"] == "attempt"


@pytest.mark.parametrize("count,accepted", [(399, False), (500, True), (651, False)])
def test_program_counts_han_before_sources_even_when_model_says_pass(count, accepted):
    model = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content='{"passed": true, "issues": []}')))
    result = asyncio.run(review_report(model, {"user_requirements": "约 500 字中文报告"},
                                      "文" * count + "\n### 来源\n" + "源" * 200))
    assert result["body_han_count"] == count
    assert result["body_han_bounds"] == [400, 650]
    assert result["passed"] == accepted


@pytest.mark.parametrize("payload,finish,expected", [
    ('{"passed":true,"issues":[]}', 'length', 'incomplete_response'),
    ('{"passed":true,"issues":[],"private":"SECRET"}', 'stop', 'extra_forbidden'),
    ('{"passed":"SECRET","issues":[]}', 'stop', 'bool_type'),
    ('{"passed":true,"issues":', 'stop', 'json_invalid'),
])
def test_failed_review_diagnostics_exclude_response_and_validation_inputs(payload, finish, expected):
    model = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(
        content=payload, response_metadata={"finish_reason": finish})))
    with pytest.raises(ReportReviewFormatError) as caught:
        asyncio.run(review_report(model, {}, "Candidate"))
    diagnostics = caught.value.diagnostics
    assert diagnostics["response_sha256"] == hashlib.sha256(payload.encode()).hexdigest()
    assert diagnostics["response_characters"] == len(payload)
    assert diagnostics["validation_error_types"] == [expected]
    assert 'SECRET' not in json.dumps(diagnostics) + str(caught.value)
    assert model.ainvoke.await_count == 1


@pytest.mark.parametrize("finish", ["stop", "length"])
def test_json_review_preserves_thinking_and_uses_only_visible_stream_content(monkeypatch, finish):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        chunks = [
            {"role": "assistant", "reasoning_content": "PRIVATE_THINKING"},
            {"content": '{"passed":true,"issues":[]}'},
            {},
        ]
        events = ''.join('data: ' + json.dumps({
            "id": "review", "object": "chat.completion.chunk", "created": 1, "model": "test/model",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish if index == 2 else None}],
        }) + '\n\n' for index, delta in enumerate(chunks))
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, text=events + 'data: [DONE]\n\n')

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            model = ChatOpenAI(model="test/model", api_key="test-key", base_url="https://test.invalid/v1",
                               http_async_client=client, max_retries=0).bind(
                extra_body={"thinking": {"type": "enabled"}}, reasoning_effort="high")
            return await review_report(model, {}, "Candidate")

    if finish == 'stop':
        result = asyncio.run(run())
        assert result["passed"] is True and "PRIVATE_THINKING" not in json.dumps(result)
    else:
        with pytest.raises(ReportReviewFormatError) as caught:
            asyncio.run(run())
        assert caught.value.diagnostics['finish_reason'] == 'length'
        assert caught.value.diagnostics['validation_error_types'] == ['incomplete_response']
        assert 'PRIVATE_THINKING' not in json.dumps(caught.value.diagnostics)
    assert len(requests) == 1
    assert requests[0]["thinking"] == {"type": "enabled"}
    assert requests[0]["reasoning_effort"] == "high"
    assert requests[0]["response_format"] == {"type": "json_object"}
    assert requests[0]["stream"] is True and "tools" not in requests[0]
