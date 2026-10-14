"""Exercise the real ChatOpenAI stream parser and retry boundary with fake HTTP."""

import asyncio
import json

import httpx
from langchain_openai import ChatOpenAI

from deep_research.model_transport import streaming_options


TOOL = {"type": "function", "function": {
    "name": "lookup", "description": "Read evidence", "parameters": {
        "type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"],
    },
}}


def event(delta, finish=None):
    return "data: " + json.dumps({
        "id": "test-completion", "object": "chat.completion.chunk", "created": 1,
        "model": "test/model", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }) + "\n\n"


def tool_response():
    return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, text=(
        event({"role": "assistant", "tool_calls": [{"index": 0, "id": "call-1", "type": "function",
                                                    "function": {"name": "lookup", "arguments": '{"query": "'}}]})
        + event({"tool_calls": [{"index": 0, "function": {"arguments": 'allowed page"}'}}]})
        + event({}, "tool_calls") + "data: [DONE]\n\n"
    ))


def test_sync_bound_tools_return_one_complete_parsed_message(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return tool_response()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        model = ChatOpenAI(model="test/model", api_key="test-key", base_url="https://test.invalid/v1", http_client=client, max_retries=0).bind_tools([TOOL])
        response = model.invoke("Read the allowed page", **streaming_options(model))
    assert requests[0]["stream"] is True
    assert response.type == "ai"
    assert response.tool_calls[0]["args"] == {"query": "allowed page"}


def test_async_bound_tools_use_stream_transport(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return tool_response()
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            model = ChatOpenAI(model="test/model", api_key="test-key", base_url="https://test.invalid/v1", http_async_client=client, max_retries=0).bind_tools([TOOL])
            return await model.ainvoke("Read the allowed page", **streaming_options(model))
    response = asyncio.run(run())
    assert requests[0]["stream"] is True
    assert response.tool_calls[0]["name"] == "lookup"
    assert response.tool_calls[0]["args"] == {"query": "allowed page"}


def test_stream_option_preserves_whole_invoke_retry(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(500, json={"error": {"message": "temporary", "type": "server_error"}})
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, text=(
            event({"role": "assistant", "content": "Complete "})
            + event({"content": "finding"}) + event({}, "stop") + "data: [DONE]\n\n"
        ))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        model = ChatOpenAI(model="test/model", api_key="test-key", base_url="https://test.invalid/v1", http_client=client, max_retries=0).with_retry(stop_after_attempt=2, wait_exponential_jitter=False)
        response = model.invoke("Compress evidence", **streaming_options(model))
    assert len(requests) == 2 and all(item["stream"] is True for item in requests)
    assert response.content == "Complete finding"


def test_other_callables_are_unchanged():
    assert streaming_options(object()) == {}
