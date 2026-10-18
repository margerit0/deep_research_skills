"""Checkpointed full-graph tests. All model/search calls are substitutes."""

import asyncio
import hashlib
import json
import os
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

for role in (
    "SCOPING",
    "SUPERVISOR",
    "RESEARCHER",
    "SUMMARIZATION",
    "COMPRESSION",
    "FINAL_REPORT",
):
    os.environ.setdefault(f"{role}_MODEL", "dummy/model")
for key in ("LLM_API_KEY", "OPENAI_API_KEY", "TAVILY_API_KEY"):
    os.environ.setdefault(key, "test-key")

from deep_research import atlas_api, model_config, multi_agent_supervisor as supervisor
from deep_research import research_agent_full as full, research_agent_scope as scope
from deep_research import research_agent_skills as worker
from deep_research.research_events import (
    capture_research_events,
    emit_research_event,
    researcher_task,
)
from deep_research.utils import format_search_output
from deep_research.workflow_contract import extract_search_sources, merge_sources


SOURCE = {"title": "Source A", "url": "https://example.com/research"}


def invoke(coro):
    return asyncio.run(coro)


def request(topic, research_id, turn_id):
    return {
        "messages": [HumanMessage(content=topic, id=turn_id)],
        "research_id": research_id,
        "turn_id": turn_id,
    }


@pytest.fixture
def harness():
    history = []

    def structured(_model, schema, prompt):
        history.append(prompt)
        if schema is scope.ResearchQuestion:
            return scope.ResearchQuestion(research_brief="Current brief")
        return scope.ClarifyWithUser(
            need_clarification=False, question="", verification="开始研究。"
        )

    async def plan(messages):
        has_result = any(
            isinstance(m, ToolMessage) and m.name == "ConductResearch" for m in messages
        )
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "done" if has_result else "task",
                    "name": "ResearchComplete" if has_result else "ConductResearch",
                    "args": {} if has_result else {"research_topic": "Current topic"},
                }
            ],
        )

    researcher = AsyncMock(
        return_value={
            "compressed_research": "Valid finding [1]",
            "raw_notes": ["Raw A"],
            "sources": [SOURCE],
        }
    )
    writer = AsyncMock(
        return_value=AIMessage(
            content="# Current report\n\nFinding [1].\n\n[1] https://example.com/research"
        )
    )
    planner = AsyncMock(side_effect=plan)
    with (
        patch.object(
            scope, "invoke_with_structured_output_fallback", side_effect=structured
        ) as scoping,
        patch.object(
            supervisor, "supervisor_model_with_tools", SimpleNamespace(ainvoke=planner)
        ),
        patch.object(
            supervisor, "researcher_agent", SimpleNamespace(ainvoke=researcher)
        ),
        patch.object(full, "writer_model", SimpleNamespace(ainvoke=writer)),
        patch.object(full, "review_report", AsyncMock(return_value={"passed": True, "issues": []})),
    ):
        yield SimpleNamespace(
            graph=full.deep_researcher_builder.compile(checkpointer=InMemorySaver()),
            config={"configurable": {"thread_id": "checkpoint-test"}},
            scoping=scoping,
            researcher=researcher,
            writer=writer,
            planner=planner,
            history=history,
        )


def test_clarification_continues_same_thread_and_duplicate_input_is_a_noop(harness):
    h = harness
    original = h.scoping.side_effect
    h.scoping.side_effect = lambda *args: scope.ClarifyWithUser(
        need_clarification=True, question="比较哪些产品？", verification=""
    )
    first_input = request("比较产品", "research-a", "turn-a")
    first = invoke(h.graph.ainvoke(first_input, h.config))
    assert first["research_status"] == "awaiting_input"
    assert not first["final_report"]
    h.writer.assert_not_awaited()
    h.researcher.assert_not_awaited()
    calls = h.scoping.call_count
    invoke(h.graph.ainvoke(first_input, h.config))
    assert h.scoping.call_count == calls
    h.scoping.side_effect = original
    final = invoke(h.graph.ainvoke(request("A 与 B", "research-a", "turn-b"), h.config))
    assert final["research_status"] == "succeeded"
    assert final["report_research_id"] == "research-a"
    assert final["active_turn_id"] == "turn-b"
    assert [m.content for m in final["messages"] if isinstance(m, HumanMessage)] == [
        "比较产品",
        "A 与 B",
    ]
    assert "比较哪些产品？" in h.history[0]
    assert final["messages"][-1].type == "ai"
    assert final["sources"] == [SOURCE]
    assert final["notes"] == ["Valid finding [1]"]


def test_new_research_clears_all_reduced_channels_and_report(harness):
    h = harness
    from deep_research.source_evidence import capture_source_evidence, record_source_evidence
    with capture_source_evidence() as evidence:
        record_source_evidence(SOURCE["url"], {"raw_content": "FIRST SOURCE SECRET"})
    h.researcher.return_value["source_evidence"] = evidence
    first = invoke(
        h.graph.ainvoke(request("FIRST SECRET TOPIC", "research-a", "turn-a"), h.config)
    )
    assert first["research_status"] == "succeeded"
    assert first["source_evidence"] == evidence
    h.history.clear()
    h.researcher.return_value = {
        "compressed_research": "New finding",
        "raw_notes": ["Raw B"],
        "sources": [SOURCE],
    }
    second = invoke(
        h.graph.ainvoke(request("SECOND TOPIC", "research-b", "turn-b"), h.config)
    )
    assert second["research_status"] == "succeeded"
    assert second["report_research_id"] == "research-b"
    assert second["notes"] == ["New finding"]
    assert second["raw_notes"] == ["Raw B"]
    assert second["source_evidence"] == []
    assert second["research_iterations"] == 2
    assert not any("FIRST SECRET TOPIC" in prompt for prompt in h.history)
    assert "Valid finding" not in str(second["supervisor_messages"])
    # Even a subsequent clarification must not expose the previous report/notes.
    h.scoping.side_effect = lambda *args: scope.ClarifyWithUser(
        need_clarification=True, question="范围？", verification=""
    )
    third = invoke(
        h.graph.ainvoke(request("THIRD TOPIC", "research-c", "turn-c"), h.config)
    )
    assert third["research_status"] == "awaiting_input"
    assert third["final_report"] == third["report_research_id"] == ""
    assert third["notes"] == third["raw_notes"] == third["supervisor_messages"] == []
    assert third["research_events"] == []
    assert third["source_evidence"] == []
    assert {event["research_id"] for event in second["research_events"]} == {
        "research-b"
    }


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("PRIVATE PROVIDER PAYLOAD"),
        {"compressed_research": "## 研究未完成\nNo results"},
        {},
    ],
)
def test_failed_research_never_calls_writer(harness, failure):
    h = harness
    if isinstance(failure, Exception):
        h.researcher.side_effect = failure
    else:
        h.researcher.return_value = failure
    result = invoke(
        h.graph.ainvoke(request("Question", "research-a", "turn-a"), h.config)
    )
    assert result["research_status"] == "failed"
    assert result["final_report"] == ""
    assert result["notes"] == []
    assert result["research_errors"]
    assert "PRIVATE PROVIDER PAYLOAD" not in json.dumps(result["research_errors"])
    h.writer.assert_not_awaited()


@pytest.mark.parametrize("summary_interrupted", [False, True])
def test_source_conditions_and_conflicts_reach_writer_through_real_nodes(
    harness, monkeypatch, summary_interrupted
):
    """Verify transport, not model semantics, with non-Python evidence."""
    from deep_research import utils
    from deep_research.state_research import Summary

    h = harness
    evidence = {
        "https://example.com/v1/pump": {
            "title": "Pump trial A",
            "raw_content": (
                "In the 2021 trial, flow improved by 12% only with clean water at 20 C. "
                "Saline workloads saw no improvement. Certification does not replace "
                "inspection of shared seals. A 20% gain was a future target, not a result."
            ),
        },
        "https://example.com/v2/pump": {
            "title": "Pump trial B",
            "raw_content": (
                "The 2024 saline trial found 8% improvement; its baseline differs "
                "from the 2021 trial, so the results cannot be directly combined. "
                "Pressure above 4 bar can damage the seal; this does not establish "
                "that lower pressures are always safe."
            ),
        },
    }

    def summarize(messages):
        prompt = messages[0].content
        body = next(item["raw_content"] for item in evidence.values()
                    if item["raw_content"] in prompt)
        if summary_interrupted:
            yield Summary(summary="Unfinished and unqualified claim", key_excerpts="")
            raise RuntimeError("stream interrupted")
        yield Summary(summary=body, key_excerpts=body)

    summary_model = SimpleNamespace(with_structured_output=lambda *a, **kw:
                                    SimpleNamespace(stream=summarize))
    monkeypatch.setattr(utils, "selected_model", lambda *a: summary_model)

    def compress(messages, **kwargs):
        tool = next(message for message in messages if message.content.startswith("Search results:"))
        assert "UNTRUSTED_INTERNAL" not in str(messages)
        assert "Unfinished and unqualified claim" not in tool.content
        for url, item in evidence.items():
            # A qualifier must still be attached to its original versioned URL.
            section = tool.content.split(f"URL: {url}\n", 1)[1].split("--- SOURCE", 1)[0]
            assert item["raw_content"] in section
        # Simulate lossy compression: source text must reach writing separately.
        return AIMessage(content="The trials were successful [1][2].")

    monkeypatch.setattr(worker, "selected_model", lambda *a, **kw:
                        SimpleNamespace(invoke=compress))

    async def research(state):
        call = AIMessage(content="UNTRUSTED_INTERNAL", tool_calls=[{
            "id": "pump-search", "name": "tavily_search", "args": {"query": "pump"},
        }])
        update = worker.tool_node({**state, "researcher_messages": [call]})
        return worker.compress_research({**state, **update, "researcher_messages": [
            HumanMessage(content="UNTRUSTED_INTERNAL", name="loaded_methodology"),
            call, *update["researcher_messages"],
        ]})

    monkeypatch.setitem(worker.tools_by_name, "tavily_search", SimpleNamespace(
        invoke=lambda args: utils.format_search_output(utils.process_search_results(evidence))))

    async def write(messages):
        for url, item in evidence.items():
            assert url in messages[-1].content
            assert item["raw_content"] in messages[-1].content
        return AIMessage(content="Comparison [1][2].\n" + "\n".join(
            f"[{index}] {url}" for index, url in enumerate(evidence, 1)))

    h.researcher.side_effect = research
    h.writer.side_effect = write
    final = invoke(h.graph.ainvoke(request("Compare pump trials", "pump", "turn"), h.config))
    assert final["research_status"] == "succeeded"
    assert {source["url"] for source in final["sources"]} == set(evidence)
    assert {item["text"] for item in final["source_evidence"]} == {
        item["raw_content"] for item in evidence.values()}
    h.writer.assert_awaited_once()


@pytest.mark.parametrize("accepted", [True, False])
def test_review_outcome_is_checkpointed_and_duplicate_turn_never_rewrites(harness, accepted):
    from deep_research.source_evidence import capture_source_evidence, record_source_evidence
    h = harness
    with capture_source_evidence() as evidence:
        record_source_evidence(SOURCE["url"], {"raw_content": "Only measured under condition A."})
    h.researcher.return_value["source_evidence"] = evidence
    conditions = [{"condition_id": 1, "condition": "The measurement requires condition A.",
                   "kind": "substantive_prerequisite", "source": {"url": SOURCE["url"],
                   "body_sha256": evidence[0]["body_sha256"], "start": 0, "end": len(evidence[0]["text"]),
                   "quote_sha256": hashlib.sha256(evidence[0]["text"].encode()).hexdigest()}}]
    full.review_report.side_effect = [
        {"passed": False, "issues": ["Missing condition A"], "body_han_count": 0,
         "body_han_bounds": [400, 650], "source_conditions": conditions},
        {"passed": accepted, "issues": [] if accepted else ["Still missing condition A"]},
    ]
    payload = request("Report the measured outcome，约 500 字中文", "review-study", "review-turn")
    result = invoke(h.graph.ainvoke(payload, h.config))
    assert result["research_status"] == ("succeeded" if accepted else "partial")
    assert bool(result["final_report"]) == accepted
    assert len(result["report_reviews"]) == 2
    assert len({item["writing_attempt_id"] for item in result["report_reviews"]}) == 2
    if accepted:
        assert result["report_writing_attempt_id"] == result["report_reviews"][-1]["writing_attempt_id"]
    assert full.review_report.await_count == h.writer.await_count == 2
    original_messages = h.writer.await_args_list[0].args[0]
    revised_messages = h.writer.await_args_list[1].args[0]
    assert revised_messages[:-1] == original_messages
    content = revised_messages[-1].content
    feedback, _ = json.JSONDecoder().raw_decode(content[content.index('{"candidate":'):])
    assert feedback["body_han_count"] == 0 and feedback["body_han_bounds"] == [400, 650]
    assert feedback["target_body_han_count"] == 500 and feedback["preferred_net_change_han"] == 500
    assert [{key: value for key, value in item.items() if key != "source_excerpt"}
            for item in feedback["source_conditions"]] == conditions
    assert feedback["source_conditions"][0]["source_excerpt"] == evidence[0]["text"]
    assert result["report_reviews"][0]["source_conditions"] == conditions
    assert feedback["issues"] == ["Missing condition A"]
    again = invoke(h.graph.ainvoke(payload, h.config))
    assert again["report_reviews"] == result["report_reviews"]
    assert full.review_report.await_count == h.writer.await_count == 2


def test_invalid_review_persists_safe_diagnostics_without_committing_or_regenerating(harness):
    from deep_research.report_review import ReportReviewFormatError
    from deep_research.source_evidence import capture_source_evidence, record_source_evidence
    h = harness
    with capture_source_evidence() as evidence:
        record_source_evidence(SOURCE["url"], {"raw_content": "Measured under condition A."})
    h.researcher.return_value["source_evidence"] = evidence
    error = ReportReviewFormatError('PRIVATE_RESPONSE', 'length', ['incomplete_response'])
    full.review_report.side_effect = error
    payload = request("Report measured outcome", "invalid-review", "invalid-review-turn")
    result = invoke(h.graph.ainvoke(payload, h.config))
    assert result["research_status"] == "partial" and result["final_report"] == ""
    assert result["report_reviews"][0]["diagnostics"] == error.diagnostics
    assert 'PRIVATE_RESPONSE' not in json.dumps(result["report_reviews"])
    assert result["source_evidence"] == evidence
    again = invoke(h.graph.ainvoke(payload, h.config))
    assert again["report_reviews"] == result["report_reviews"]
    assert full.review_report.await_count == h.writer.await_count == 1


def test_partial_parallel_failure_preserves_successful_sibling(harness):
    h = harness
    h.planner.side_effect = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "one",
                    "name": "ConductResearch",
                    "args": {"research_topic": "One"},
                },
                {
                    "id": "two",
                    "name": "ConductResearch",
                    "args": {"research_topic": "Two"},
                },
            ],
        ),
        AIMessage(
            content="",
            tool_calls=[{"id": "done", "name": "ResearchComplete", "args": {}}],
        ),
    ]
    h.researcher.side_effect = [
        h.researcher.return_value,
        RuntimeError("researcher unavailable"),
    ]
    result = invoke(
        h.graph.ainvoke(request("Question", "research-a", "turn-a"), h.config)
    )
    assert result["research_status"] == "partial"
    assert result["final_report"]
    assert result["notes"] == ["Valid finding [1]"]
    assert result["sources"] == [SOURCE]


@pytest.mark.parametrize(
    "response",
    [
        RuntimeError("PRIVATE WRITER PAYLOAD"),
        AIMessage(content=""),
        AIMessage(content="## 研究未完成"),
    ],
)
def test_writer_failure_is_partial_with_notes(harness, response):
    h = harness
    if isinstance(response, Exception):
        h.writer.side_effect = response
    else:
        h.writer.return_value = response
    result = invoke(
        h.graph.ainvoke(request("Question", "research-a", "turn-a"), h.config)
    )
    assert result["research_status"] == "partial"
    assert result["final_report"] == result["report_research_id"] == ""
    assert result["notes"] and result["sources"]
    assert "PRIVATE WRITER PAYLOAD" not in str(result["research_errors"])


def test_supervisor_model_exception_is_failure(harness):
    harness.planner.side_effect = RuntimeError("Unavailable")
    result = invoke(
        harness.graph.ainvoke(
            request("Question", "research-a", "turn-a"), harness.config
        )
    )
    assert result["research_status"] == "failed"
    harness.writer.assert_not_awaited()


def test_scoping_failure_has_safe_status(harness):
    harness.scoping.side_effect = RuntimeError("sensitive gateway payload")
    result = invoke(
        harness.graph.ainvoke(
            request("Question", "research-a", "turn-a"), harness.config
        )
    )
    assert result["research_status"] == "failed"
    assert result["research_errors"][0]["code"] == "clarification_failed"
    assert "sensitive" not in str(result["research_errors"])


def test_thinking_and_failed_notes_are_not_research_evidence():
    messages = [
        ToolMessage(content="Private strategy", name="think_tool", tool_call_id="1"),
        ToolMessage(
            content="## 研究未完成\nNothing", name="ConductResearch", tool_call_id="2"
        ),
        ToolMessage(content="Valid finding", name="ConductResearch", tool_call_id="3"),
    ]
    assert supervisor.get_notes_from_tool_calls(messages) == ["Valid finding"]


def test_original_requirements_survive_brief_and_delegation_omissions(harness):
    h = harness
    original = (
        "先调用 load_skill，skill_name=product-comparison。"
        "仅使用 https://example.com/research。请用简单关键词查询，约 500 字。"
    )
    seen = []

    def research(messages):
        seen.append(messages)
        if any(isinstance(m, ToolMessage) and m.name == "tavily_search" for m in messages):
            return AIMessage(content="Ready to compress")
        return AIMessage(content="", tool_calls=[{
            "id": "search", "name": "tavily_search", "args": {"query": "simple keywords"},
        }])

    search = SimpleNamespace(invoke=lambda args: format_search_output({
        SOURCE["url"]: {"title": SOURCE["title"], "content": "Conditional evidence"},
    }))
    with (
        patch.object(supervisor, "researcher_agent", worker.researcher_agent_skills),
        patch.object(worker, "model_with_tools", SimpleNamespace(invoke=research)),
        patch.object(worker, "compress_model", SimpleNamespace(invoke=lambda _: AIMessage(content="Conditional finding [1]"))),
        patch.dict(worker.tools_by_name, {"tavily_search": search}),
    ):
        result = invoke(h.graph.ainvoke(request(original, "r-constraints", "t-constraints"), h.config))
    assert result["research_status"] == "succeeded"
    assert result["research_brief"] == "Current brief"  # model omitted every requirement
    assert result["user_requirements"] == original
    assert result["research_constraints"] == {
        "required_skills": ["product-comparison"],
        "allowed_source_urls": [SOURCE["url"]],
    }
    assert original in seen[0][0].content and "Current brief" in seen[0][0].content
    assert seen[0][1].content == "Current topic"  # scope remains distinct
    assert any(m.name == "loaded_methodology" and "产品对比方法论" in m.content for m in seen[0])
    events = result["research_events"]
    loaded = next(e for e in events if e["kind"] == "tool_finished" and e.get("tool") == "load_skill")
    searched = next(e for e in events if e["kind"] == "tool_started" and e.get("tool") == "tavily_search")
    assert loaded["query"] == "product-comparison"
    assert loaded["sequence"] < searched["sequence"]
    assert "产品对比方法论" not in str(result["raw_notes"])
    assert original in h.writer.call_args.args[0][0].content


def test_writer_cannot_publish_a_url_not_returned_by_search(harness):
    harness.writer.return_value = AIMessage(content="Unsupported fact [1].\n[1] https://example.com/other-version")
    result = invoke(harness.graph.ainvoke(request("Question", "r-citation", "t-citation"), harness.config))
    assert result["research_status"] == "partial"
    assert result["final_report"] == ""
    assert result["sources"] == [SOURCE]
    assert result["notes"]


def test_sources_are_deduplicated_from_search_records_and_urls_are_safe():
    output = "--- SOURCE 1: A ---\nURL: https://example.com/a\n\nSUMMARY: text"
    source = {"title": "A", "url": "https://example.com/a"}
    assert extract_search_sources(output) == [source]
    assert merge_sources(
        [source], [source, {"title": "Bad", "url": "javascript:alert(1)"}]
    ) == [source]
    assert (
        merge_sources(
            [{"title": "Credentials", "url": "https://user:secret@example.com"}]
        )
        == []
    )


def test_config_endpoint_only_exposes_constructed_model_whitelist():
    payload = invoke(atlas_api.config(None))
    assert payload.status_code == 200
    config = json.loads(payload.body)
    assert config["graph_id"] == "research_agent_full"
    assert config["skills_mode"] == "auto"
    assert len(config["models"]) == 6
    assert all(
        set(model) == {"role", "model", "provider", "max_tokens"}
        for model in config["models"]
    )
    assert "test-key" not in payload.body.decode()
    with patch.dict(model_config._model_snapshots, {}, clear=True):
        assert invoke(atlas_api.config(None)).status_code == 503


def test_qwen_payload_diagnostic_survives_full_graph_without_credentials(
    harness, caplog
):
    harness.scoping.side_effect = ValueError(
        "Raw HTTP fallback received invalid choices payload (attempt 2/2): "
        "model=Qwen/example, choices_type=NoneType, choices_len=n/a, "
        "usage={'total_tokens': 0}, keys=['choices', 'usage'], base_url='https://private-endpoint'"
    )
    result = invoke(
        harness.graph.ainvoke(
            request("Question", "research-a", "turn-a"), harness.config
        )
    )
    assert result["research_status"] == "failed"
    assert "choices_type=NoneType" in caplog.text
    assert "total_tokens" in caplog.text
    assert "private-endpoint" not in caplog.text
    assert "payload_diagnostic" not in str(result["research_errors"])


def test_research_events_stream_before_child_finishes_and_match_checkpoint(harness):
    """Use the actual nested graph and sync tools, not a mocked event writer."""
    release_search = threading.Event()

    def research(messages):
        used = {
            message.name for message in messages if isinstance(message, ToolMessage)
        }
        if "load_skill" not in used:
            calls = [
                {
                    "id": "skill",
                    "name": "load_skill",
                    "args": {"skill_name": "academic-research"},
                }
            ]
        elif "tavily_search" not in used:
            calls = [
                {
                    "id": "search",
                    "name": "tavily_search",
                    "args": {"query": "public query"},
                },
                {
                    "id": "think",
                    "name": "think_tool",
                    "args": {"reflection": "PRIVATE REASONING"},
                },
            ]
        else:
            calls = []
        return AIMessage(content="PRIVATE MODEL TEXT", tool_calls=calls)

    def search(_args):
        assert release_search.wait(10), (
            "The custom event must arrive while the child is running"
        )
        return format_search_output(
            {SOURCE["url"]: {"title": SOURCE["title"], "content": "RAW TOOL TEXT"}}
        )

    async def collect():
        seen, final = [], None
        try:
            async for mode, value in harness.graph.astream(
                request("Question", "research-stream", "turn-stream"),
                harness.config,
                stream_mode=["custom", "values"],
            ):
                if mode == "custom":
                    assert value["type"] in {"atlas.research_event", "atlas.report_event"}
                    if value["type"] == "atlas.report_event":
                        continue
                    event = value["event"]
                    seen.append(event)
                    if (
                        event["kind"] == "tool_started"
                        and event["tool"] == "tavily_search"
                    ):
                        release_search.set()
                else:
                    final = value
        finally:
            release_search.set()
        return seen, final

    with (
        patch.object(supervisor, "researcher_agent", worker.researcher_agent_skills),
        patch.object(worker, "model_with_tools", SimpleNamespace(invoke=research)),
        patch.object(
            worker,
            "compress_model",
            SimpleNamespace(
                invoke=lambda _: AIMessage(content="Valid compressed notes")
            ),
        ),
        patch.dict(
            worker.tools_by_name,
            {
                "tavily_search": SimpleNamespace(invoke=search),
                "load_skill": SimpleNamespace(invoke=lambda _: "PRIVATE SKILL BODY"),
                "think_tool": SimpleNamespace(invoke=lambda _: "PRIVATE REASONING"),
            },
        ),
    ):
        events, final = invoke(collect())
    assert final["research_status"] == "succeeded"
    assert events == final["research_events"]
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert {event["research_id"] for event in events} == {"research-stream"}
    assert {event["turn_id"] for event in events} == {"turn-stream"}
    assert len({event["task_id"] for event in events}) == 1
    assert events[0]["kind"] == "delegated"
    assert events[-1]["kind"] == "completed"
    assert events[-1]["output"] == "Valid compressed notes"
    assert events[-1]["sources"] == [SOURCE]
    assert {"compression_started", "compression_finished"} <= {
        event["kind"] for event in events
    }
    serialized = json.dumps(events)
    assert "PRIVATE" not in serialized and "RAW TOOL TEXT" not in serialized
    assert "public query" in serialized and "academic-research" in serialized
    assert harness.graph.get_state(harness.config).values["research_events"] == events


def test_parallel_and_later_delegations_keep_distinct_task_outcomes(harness):
    def delegate(call_id, topic):
        return {
            "id": call_id,
            "name": "ConductResearch",
            "args": {"research_topic": topic},
        }

    harness.planner.side_effect = [
        AIMessage(
            content="", tool_calls=[delegate("same-id", "One"), delegate("two", "Two")]
        ),
        AIMessage(content="", tool_calls=[delegate("same-id", "Three")]),
        AIMessage(
            content="",
            tool_calls=[{"id": "done", "name": "ResearchComplete", "args": {}}],
        ),
    ]

    async def investigate(state):
        if state["research_topic"] == "Two":
            raise RuntimeError("PRIVATE PROVIDER PAYLOAD")
        await asyncio.sleep(0)
        return {"compressed_research": state["research_topic"], "sources": [SOURCE]}

    harness.researcher.side_effect = investigate
    final = invoke(
        harness.graph.ainvoke(
            request("Question", "research-rounds", "turn-rounds"), harness.config
        )
    )
    events = final["research_events"]
    delegated = [event for event in events if event["kind"] == "delegated"]
    assert [(event["round"], event["topic"]) for event in delegated] == [
        (1, "One"),
        (1, "Two"),
        (2, "Three"),
    ]
    assert len({event["task_id"] for event in delegated}) == 3
    outcomes = {
        event["task_id"]: event["kind"]
        for event in events
        if event["kind"] in {"failed", "completed"}
    }
    assert [outcomes[event["task_id"]] for event in delegated] == [
        "completed",
        "failed",
        "completed",
    ]
    assert final["research_status"] == "partial" and final["final_report"]
    assert "PRIVATE PROVIDER PAYLOAD" not in str(events)


def test_simultaneous_threads_do_not_share_event_recorders(harness):
    async def run_both():
        return await asyncio.gather(
            *[
                harness.graph.ainvoke(
                    request("Question", f"research-{i}", f"turn-{i}"),
                    {"configurable": {"thread_id": f"thread-{i}"}},
                )
                for i in range(2)
            ]
        )

    for index, result in enumerate(invoke(run_both())):
        assert result["research_status"] == "succeeded"
        assert result["research_events"]
        assert {event["research_id"] for event in result["research_events"]} == {
            f"research-{index}"
        }
        assert {event["turn_id"] for event in result["research_events"]} == {
            f"turn-{index}"
        }


def test_event_payload_redaction_and_stream_failure_do_not_break_research(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "secret-event-test-key")
    with capture_research_events("research", "turn") as events:
        with researcher_task("call", "topic secret-event-test-key", 1):
            emit_research_event(
                "tool_started", tool="think_tool", query="PRIVATE REASONING"
            )
            emit_research_event(
                "tool_started",
                tool="tavily_search",
                query="query secret-event-test-key",
            )
            emit_research_event("completed", output="x" * 9000, sources=[SOURCE])
    assert "secret-event-test-key" not in str(events)
    assert "PRIVATE REASONING" not in str(events)
    assert "[redacted]" in str(events)
    assert events[-1]["output"].endswith("…（已截断）")
    assert len(events[-1]["output"]) < 8050
    # A disconnected observer never changes the graph's business outcome.
    with patch(
        "deep_research.research_events.get_stream_writer",
        return_value=lambda _: (_ for _ in ()).throw(RuntimeError("closed")),
    ):
        with capture_research_events("research", "turn") as events:
            with researcher_task("call", "topic", 1):
                emit_research_event("completed", output="valid result")
    assert events[-1]["kind"] == "completed"
