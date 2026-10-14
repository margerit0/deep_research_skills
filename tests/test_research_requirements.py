"""User constraints at real node/tool boundaries; external calls are substitutes."""

import asyncio
from contextlib import nullcontext
from copy import deepcopy
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langchain_core.messages import ToolMessage

for role in ("SCOPING", "SUPERVISOR", "RESEARCHER", "SUMMARIZATION", "COMPRESSION", "FINAL_REPORT"):
    os.environ.setdefault(f"{role}_MODEL", "dummy/model")
for key in ("LLM_API_KEY", "OPENAI_API_KEY", "TAVILY_API_KEY"):
    os.environ.setdefault(key, "test-key")

from deep_research import research_requirements as requirements, utils
from deep_research import research_agent_skills as worker, run_configuration
from deep_research.research_events import capture_research_events, researcher_task
from deep_research.workflow_contract import extract_search_sources


URL_A = "https://example.com/v1/a"
URL_B = "https://example.com/v1/b"
OTHER = "https://example.com/current/b"


@pytest.mark.parametrize("text", [
    f"资料范围固定为两篇指南：{URL_A} 和 {URL_B}；不要扩展。",
    f"Use only these pages:\n- {URL_A}\n- {URL_B}\n\nWrite briefly.",
    f"仅依据以下页面：{URL_A} 和 {URL_B}。",
    f"Sources are limited to {URL_A} and {URL_B}.",
])
def test_explicit_page_lists_are_generic_and_version_exact(text):
    constraints = requirements.resolve_constraints([text])
    assert constraints["allowed_source_urls"] == [URL_A, URL_B]
    assert requirements.allowed_sources([{"url": OTHER}], constraints) == []
    assert requirements.allowed_sources([{"url": URL_A + "#section"}], constraints)
    assert not requirements.allowed_sources([{"url": URL_A + "?different=1"}], constraints)


def test_mentions_preferences_and_query_templates_do_not_create_page_scope():
    for text in [f"参考 {URL_A}，还可以找其他证据。", f"Prefer official sources like {URL_A}",
                 f"请用 site:example.com 检索。示例：{URL_A}"]:
        assert requirements.resolve_constraints([text])["allowed_source_urls"] is None
    resolved = requirements.resolve_constraints([
        f"仅使用 {URL_A}。", f"更正：仅使用 {URL_B}。"
    ])
    assert resolved["allowed_source_urls"] == [URL_B]


def test_named_skill_does_not_depend_on_topic_or_known_skill_catalog():
    resolved = requirements.resolve_constraints([
        "研究员必须先调用 load_skill 工具，skill_name 使用 product-comparison，再检索。",
        '还需 load_skill(skill_name="unknown-method")。',
    ])
    assert resolved["required_skills"] == ["product-comparison", "unknown-method"]


def test_sources_are_filtered_before_summarization_and_raw_hits_remain_unchanged(monkeypatch):
    raw = [{"results": [
        {"url": URL_A, "title": "A", "raw_content": "allowed conditional facts"},
        {"url": OTHER, "title": "Wrong version", "raw_content": "FORBIDDEN_CONTENT"},
    ]}]
    original = deepcopy(raw)
    monkeypatch.setattr(utils, "tavily_search_multiple", lambda *a, **kw: raw)
    get = Mock(side_effect=lambda url, **kw: nullcontext(SimpleNamespace(status_code=200, url=url, headers={})))
    monkeypatch.setattr(requirements.requests, "get", get)
    summarize = Mock(return_value="facts with conditions")
    monkeypatch.setattr(utils, "summarize_webpage_content", summarize)
    with requirements.source_scope({"allowed_source_urls": [URL_A]}) as audit:
        output = utils.tavily_search.invoke({"query": "simple site:example.com"})
    assert [entry["decision"] for entry in audit] == ["accepted", "out_of_scope"]
    assert [source["url"] for source in extract_search_sources(output)] == [URL_A]
    summarize.assert_called_once_with("allowed conditional facts")
    get.assert_called_once()
    assert get.call_args.kwargs["allow_redirects"] is False
    assert get.call_args.kwargs.get("verify", True) is True
    assert "FORBIDDEN_CONTENT" not in output and OTHER not in output
    assert raw == original


@pytest.mark.parametrize("scenario,reason", [
    ("redirect", "redirect_out_of_scope"),
    ("metadata", "redirect_out_of_scope"),
    ("http", "source_http_error"),
    ("network", "source_unverified"),
])
def test_unverified_or_wrong_version_redirects_never_become_evidence(monkeypatch, scenario, reason):
    result = {"url": URL_A, "title": "A", "content": "Never consume"}
    if scenario == "metadata":
        result["final_url"] = OTHER
    def response(url, **kwargs):
        if scenario == "network":
            raise requirements.requests.ConnectionError("PRIVATE TRANSPORT DETAILS")
        return nullcontext(SimpleNamespace(
            status_code=302 if scenario == "redirect" else 403,
            url=url, headers={"Location": OTHER},
        ))
    get = Mock(side_effect=response)
    monkeypatch.setattr(requirements.requests, "get", get)
    with requirements.source_scope({"allowed_source_urls": [URL_A]}) as audit:
        assert requirements.filter_search_results([{"results": [result]}]) == [{"results": []}]
    assert audit[0]["decision"] == reason
    assert get.call_count == (0 if scenario == "metadata" else 1)
    assert "PRIVATE" not in str(audit)


def test_empty_compliant_results_prevent_compression(monkeypatch):
    monkeypatch.setattr(requirements.requests, "get", Mock(side_effect=requirements.requests.ConnectionError("unavailable")))
    monkeypatch.setattr(utils, "tavily_search_multiple", lambda *a, **kw: [
        {"results": [{"url": OTHER, "title": "Wrong", "raw_content": "wrong evidence"}]}
    ])
    compressor = Mock()
    monkeypatch.setattr(worker, "compress_model", SimpleNamespace(invoke=compressor))
    with requirements.source_scope({"allowed_source_urls": [URL_A]}):
        output = utils.tavily_search.invoke({"query": "example"})
    result = worker.compress_research({"researcher_messages": [
        ToolMessage(content=output, name="tavily_search", tool_call_id="search")
    ]})
    assert result["compressed_research"].startswith("## 研究未完成")
    assert result["sources"] == []
    compressor.assert_not_called()


def test_specified_page_read_is_real_evidence_with_separate_provenance(monkeypatch):
    raw = [{"results": [{"url": OTHER, "title": "Wrong version", "raw_content": "FORBIDDEN CONTENT"}]}]
    monkeypatch.setattr(utils, "tavily_search_multiple", lambda *a, **kw: raw)
    def response(url, **kwargs):
        return nullcontext(SimpleNamespace(
            status_code=200, url=url, headers={"Content-Type": "text/html; charset=utf-8"},
            iter_content=lambda **kwargs: iter([b"<html><title>Fixed version</title><script>IGNORE SCRIPT</script><p>Measured only on sample A.</p></html>"]),
        ))
    get = Mock(side_effect=response)
    monkeypatch.setattr(requirements.requests, "get", get)
    seen = []
    def summarize(body):
        seen.append(body)
        return "Measured only on sample A."
    monkeypatch.setattr(utils, "summarize_webpage_content", summarize)
    with requirements.source_scope({"allowed_source_urls": [URL_A, URL_B]}) as audit:
        output = utils.tavily_search.invoke({"query": "simple keywords"})
    assert len(seen) == 2 and all("only on sample A" in body for body in seen)
    assert "FORBIDDEN" not in str(seen) and "IGNORE SCRIPT" not in str(seen)
    assert {call.args[0] for call in get.call_args_list} == {URL_A, URL_B}
    assert [(entry["retrieval"], entry["decision"]) for entry in audit] == [
        ("search", "out_of_scope"), ("specified_url", "accepted"), ("specified_url", "accepted"),
    ]
    assert extract_search_sources(output) == [
        {"title": "Fixed version", "url": url, "retrieval": "specified_url"} for url in (URL_A, URL_B)
    ]
    assert raw[0]["results"][0]["url"] == OTHER


def test_direct_read_does_not_follow_outside_redirects_or_invent_urls(monkeypatch):
    get = Mock(return_value=nullcontext(SimpleNamespace(
        status_code=302, url=URL_A, headers={"Location": OTHER},
    )))
    monkeypatch.setattr(requirements.requests, "get", get)
    with requirements.source_scope({"allowed_source_urls": [URL_A]}) as audit:
        assert requirements.retrieve_specified_sources() == [{"results": []}]
    get.assert_called_once()
    assert audit == [{"url": URL_A, "decision": "redirect_out_of_scope", "http_status": 302, "retrieval": "specified_url"}]


def test_recovery_digest_binds_new_requirements_without_changing_legacy_shape():
    from deep_research.submission_journal import digest, state_digest
    legacy_keys = ("active_research_id", "active_turn_id", "research_status", "research_phase",
                   "research_brief", "notes", "sources", "research_errors", "supervisor_status",
                   "effective_config", "final_report", "report_research_id")
    legacy = {"notes": ["finding"], "messages": []}
    assert state_digest(legacy) == digest({**{key: legacy.get(key) for key in legacy_keys}, "messages": []})
    current = {**legacy, "user_requirements": "Original scope", "research_constraints": {"allowed_source_urls": [URL_A]}}
    assert state_digest(current) != state_digest({**current, "user_requirements": "Changed scope"})
    assert state_digest(current) != state_digest({**current, "research_constraints": {"allowed_source_urls": [URL_B]}})


@pytest.mark.parametrize("available,name,reason", [
    ({}, "product-comparison", "禁用全部"),
    ({"academic-research": {"body": "available"}}, "product-comparison", "允许集合"),
    (None, "unknown-method", "不存在"),
])
def test_required_disabled_disallowed_or_unknown_skill_fails_before_model_and_search(monkeypatch, available, name, reason):
    monkeypatch.setattr(run_configuration, "active_skills", lambda: available)
    with capture_research_events("r", "t") as events, researcher_task("call", "topic", 1):
        command = worker.prepare_requirements({"research_topic": f"先加载 {name}"})
    assert command.goto == "__end__"
    assert reason in command.update["compressed_research"]
    assert [(event["kind"], event.get("tool")) for event in events[1:]] == [
        ("tool_started", "load_skill"), ("tool_failed", "load_skill")
    ]
    assert command.update["sources"] == []


def test_parallel_scopes_and_summary_threads_do_not_leak(monkeypatch):
    raw = [{"results": [{"url": url, "title": url, "raw_content": url} for url in (URL_A, URL_B)]}]
    monkeypatch.setattr(utils, "tavily_search_multiple", lambda *a, **kw: raw)
    monkeypatch.setattr(requirements.requests, "get", lambda url, **kw: nullcontext(
        SimpleNamespace(status_code=200, url=url, headers={})))
    def summarize(text):
        assert requirements._source_scope.get().allowed == {text}
        return text
    monkeypatch.setattr(utils, "summarize_webpage_content", summarize)
    async def one(url):
        with requirements.source_scope({"allowed_source_urls": [url]}) as audit:
            result = await asyncio.to_thread(utils.tavily_search.invoke, {"query": "test"})
            return result, audit
    async def both():
        return await asyncio.gather(one(URL_A), one(URL_B))
    for url, (output, audit) in zip((URL_A, URL_B), asyncio.run(both())):
        assert [source["url"] for source in extract_search_sources(output)] == [url]
        assert sum(entry["decision"] == "accepted" for entry in audit) == 1
    assert requirements._source_scope.get() is None


def test_report_urls_must_come_from_consumed_sources():
    sources = [{"url": URL_A}]
    assert requirements.report_citations_within_sources(f"[1] Source: {URL_A}#section", sources)
    assert not requirements.report_citations_within_sources(f"[1] Source: {OTHER}", sources)


def test_summary_outage_keeps_short_source_qualifiers_and_safe_diagnostics(monkeypatch, caplog):
    model = SimpleNamespace(with_structured_output=Mock(side_effect=RuntimeError("PRIVATE PROVIDER BODY")))
    monkeypatch.setattr(utils, "selected_model", lambda *a: model)
    body = "Background. " * 300 + "Only when concurrently modified. Stable ABI is not supported."
    output = utils.summarize_webpage_content(body)
    assert body in output
    assert "摘要调用失败" in output
    assert "PRIVATE PROVIDER BODY" not in caplog.text
    assert "RuntimeError" in caplog.text


def test_summary_outage_marks_truncated_large_source_as_incomplete(monkeypatch):
    model = SimpleNamespace(with_structured_output=Mock(side_effect=RuntimeError("unavailable")))
    monkeypatch.setattr(utils, "selected_model", lambda *a: model)
    output = utils.summarize_webpage_content("x" * 30000 + "UNCOVERED TAIL")
    assert "仅为前段" in output and "未覆盖部分不能据此推断" in output
    assert "UNCOVERED TAIL" not in output
    assert len(output) < 25000


def test_summary_stream_uses_final_structured_value_and_closes_iterator(monkeypatch):
    from deep_research.state_research import Summary
    closed = []
    def stream(messages):
        try:
            yield Summary(summary="Partial", key_excerpts="")
            yield Summary(summary="Measured on workload A only", key_excerpts="Not a universal guarantee")
        finally:
            closed.append(True)
    invoke = Mock(side_effect=AssertionError("Must use streaming when available"))
    model = SimpleNamespace(with_structured_output=lambda *a, **kw: SimpleNamespace(stream=stream, invoke=invoke))
    monkeypatch.setattr(utils, "selected_model", lambda *a: model)
    result = utils.summarize_webpage_content("actual source")
    assert "Measured on workload A only" in result and "Not a universal guarantee" in result
    assert "Partial" not in result and closed == [True]
    invoke.assert_not_called()


def test_interrupted_summary_stream_falls_back_to_source_not_partial_claims(monkeypatch):
    from deep_research.state_research import Summary
    def stream(messages):
        yield Summary(summary="An unfinished claim", key_excerpts="")
        raise RuntimeError("stream ended early")
    model = SimpleNamespace(with_structured_output=lambda *a, **kw: SimpleNamespace(stream=stream))
    monkeypatch.setattr(utils, "selected_model", lambda *a: model)
    result = utils.summarize_webpage_content("Original evidence with conditions")
    assert "Original evidence with conditions" in result
    assert "An unfinished claim" not in result


@pytest.mark.parametrize("url", [
    "https://example.com/Topic_(version_1)",
    "https://example.com/search?q=why?",
    "https://example.com/a?query=(one)&version=1",
])
def test_url_constraints_and_citations_preserve_real_path_and_query_syntax(url):
    text = f"Use only [this page]({url})."
    assert requirements.resolve_constraints([text])["allowed_source_urls"] == [url]
    assert requirements.report_citations_within_sources(f"[1] [Source]({url})", [{"url": url}])
