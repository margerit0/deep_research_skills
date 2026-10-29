"""Wire-level checks: complete streams, strict schema, and shared Qwen fallback."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from langchain_openai import ChatOpenAI
from langchain_core.rate_limiters import BaseRateLimiter
from pydantic import BaseModel, ConfigDict

from deep_research.structured_output_fallback import (
    StructuredOutputStreamError, invoke_with_structured_output_fallback,
    structured_output_strategy,
)


class Brief(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    research_brief: str


def event(payload):
    return 'data: ' + json.dumps(payload, ensure_ascii=False) + '\r\n\r\n'


def stream(text='{"research_brief":"中文简报"}', finish='stop', done=True):
    body = ': heartbeat\r\n\r\n'
    for part in [text[:12], text[12:]]:
        body += event({'choices': [{'index': 0, 'delta': {'content': part}}]})
    if finish is not None:
        body += event({'choices': [{'index': 0, 'delta': {}, 'finish_reason': finish}]})
    body += event({'choices': [], 'usage': {'prompt_tokens': 5, 'completion_tokens': 0}})
    return body + ('data: [DONE]\r\n\r\n' if done else '')


def model_for(handler, **kwargs):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return ChatOpenAI(model='z-ai/glm-5.3', api_key='test', base_url='https://model.invalid/v1',
                      http_client=client, max_retries=0,
                      metadata={'structured_output_strategy': 'json_object'}, **kwargs)


def test_json_object_uses_one_streamed_request_and_keeps_model_options():
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=stream().encode())
    limiter = Mock(spec=BaseRateLimiter)
    model = model_for(handler, rate_limiter=limiter, temperature=0.25)
    result = invoke_with_structured_output_fallback(model.bind(max_tokens=1234, reasoning_effort='high'), Brief, 'frozen input')
    assert result.research_brief == '中文简报'
    assert len(requests) == 1
    assert requests[0]['stream'] is True
    assert requests[0]['response_format'] == {'type': 'json_object'}
    assert requests[0].get('max_completion_tokens', requests[0].get('max_tokens')) == 1234
    assert requests[0]['reasoning_effort'] == 'high'
    assert requests[0]['temperature'] == 0.25
    assert 'tools' not in requests[0]
    limiter.acquire.assert_called_once_with(blocking=True)


@pytest.mark.parametrize('body,reason', [
    (stream(done=False), 'incomplete_response'),
    (stream(finish=None), 'incomplete_response'),
    (stream(finish='length'), 'incomplete_response'),
    (stream(text='{"research_brief":"cut off'), 'schema_validation'),
    (stream(text='{"research_brief":123}'), 'schema_validation'),
    (stream(text='{"research_brief":"ok","extra":"PRIVATE"}'), 'schema_validation'),
    (stream(text='```json\n{"research_brief":"ok"}\n```'), 'schema_validation'),
])
def test_unusable_streams_are_rejected_without_repair_or_retry(body, reason):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, text=body)
    with pytest.raises(StructuredOutputStreamError) as caught:
        invoke_with_structured_output_fallback(model_for(handler), Brief, 'input')
    assert caught.value.diagnostics['reason'] == reason
    assert len(calls) == 1
    assert 'PRIVATE' not in str(caught.value) + json.dumps(caught.value.diagnostics)


@pytest.mark.parametrize('event_prefix', ['', 'event: error\r\n'])
def test_http_200_with_stream_error_keeps_safe_diagnostics(event_prefix):
    calls = []
    def handler(request):
        calls.append(request)
        body = stream(done=False) + event_prefix + event({'error': {'message': 'PRIVATE', 'code': 'request_timeout'}})
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, text=body)
    with pytest.raises(StructuredOutputStreamError) as caught:
        invoke_with_structured_output_fallback(model_for(handler), Brief, 'input')
    assert caught.value.diagnostics['provider_error']['code'] == 'request_timeout'
    assert 'PRIVATE' not in str(caught.value) + json.dumps(caught.value.diagnostics)
    assert len(calls) == 1


def test_qwen_null_choices_retries_twice_with_no_think_and_diagnostics():
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        body = event({'model': 'Qwen/test', 'object': '', 'choices': None, 'usage': {'total_tokens': 0}}) + 'data: [DONE]\n\n'
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, text=body)
    model = model_for(handler).model_copy(update={'model_name': 'Qwen/test'})
    with pytest.raises(ValueError, match='choices_type=NoneType'):
        invoke_with_structured_output_fallback(model, Brief, 'input')
    assert len(requests) == 2
    assert all(r['messages'][0]['content'].startswith('/no_think\n') and r['enable_thinking'] is False for r in requests)


def test_default_native_and_explicit_precedence():
    assert structured_output_strategy(SimpleNamespace()) == 'native'
    assert structured_output_strategy(SimpleNamespace(metadata={'structured_output_strategy': 'json_object'}), 'native') == 'native'
    with pytest.raises(ValueError, match='Unknown'):
        structured_output_strategy(SimpleNamespace(), 'unsupported')


def test_summary_opt_in_uses_same_helper(monkeypatch):
    for key, value in {'SUMMARIZATION_MODEL': 'dummy/model', 'LLM_API_KEY': 'test',
                       'OPENAI_API_KEY': 'test', 'TAVILY_API_KEY': 'test'}.items():
        monkeypatch.setenv(key, value)
    from deep_research import utils
    from deep_research.state_research import Summary
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        text = json.dumps({'summary': 'summary', 'key_excerpts': 'quote'})
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, text=stream(text=text))
    model = model_for(handler)
    monkeypatch.setattr(utils, 'summarization_model', model)
    monkeypatch.setattr(utils, 'selected_model', lambda role, fallback: fallback)
    result = utils.summarize_webpage_content('actual source')
    assert '<summary>\nsummary\n</summary>' in result
    assert len(calls) == 1 and calls[0]['response_format']['type'] == 'json_object'
    assert json.dumps(Summary.model_json_schema(), ensure_ascii=False) in calls[0]['messages'][0]['content']
