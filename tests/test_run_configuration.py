"""Immutable configuration and context isolation; all models are substitutes."""

import asyncio
from copy import deepcopy
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

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

from deep_research import (
    run_configuration as config,
    model_config,
    skills_loader,
    utils,
)
from deep_research import research_agent_full as full
from deep_research.submission_journal import SubmissionJournal, SubmissionConflict
from deep_research.structured_output_fallback import model_connection


@pytest.fixture
def directory(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "archive_path", lambda: tmp_path / "configs.sqlite3")
    monkeypatch.setattr(config, "_definitions", {})
    monkeypatch.setattr(config, "_defaults", {})
    monkeypatch.setattr(config, "_models", {})
    for index, role in enumerate(config.ROLES):
        config.register_model(
            role,
            {
                "model": f"fixture/{index % 2}",
                "provider": "openai",
                "max_tokens": 100 + index % 2,
            },
            "https://private-gateway.invalid/v1",
        )
    return config.catalog()


def selection(directory, index=0, allowed=None):
    return {
        "version": 1,
        "models": dict.fromkeys(config.ROLES, directory["models"][index]["id"]),
        "skills": {
            "mode": "auto" if allowed is None else "manual",
            "allowed": allowed or [],
        },
    }


def test_snapshot_archive_survives_defaults_skills_and_process_memory_changes(
    directory, monkeypatch
):
    selected = config.resolve_selection(
        selection(directory, allowed=["academic-research"])
    )
    original = deepcopy(selected)
    body = skills_loader.SKILLS_BODY["academic-research"]
    monkeypatch.setattr(config, "_definitions", {})
    monkeypatch.setattr(config, "_defaults", {})
    monkeypatch.setattr(skills_loader, "SKILLS_BODY", {"academic-research": "changed"})
    config.validate_snapshot(selected)
    with config.configuration_scope(selected):
        assert (
            skills_loader.load_skill.invoke({"skill_name": "academic-research"}) == body
        )
        assert "product-comparison" not in skills_loader.format_skills_index()
        denied = skills_loader.load_skill.invoke({"skill_name": "product-comparison"})
        assert denied.startswith("错误：")
    assert selected == original
    assert "private-gateway" not in json.dumps(selected)
    assert "test-key" not in json.dumps(selected)


@pytest.mark.parametrize(
    "bad",
    [
        "version",
        "missing_role",
        "unknown_model",
        "unknown_skill",
        "duplicate_skill",
        "auto_allowed",
    ],
)
def test_invalid_selection_is_rejected(directory, bad):
    value = selection(directory)
    if bad == "version":
        value["version"] = 2
    if bad == "missing_role":
        value["models"].pop("SCOPING")
    if bad == "unknown_model":
        value["models"]["SCOPING"] = "attacker/model"
    if bad == "unknown_skill":
        value["skills"] = {"mode": "manual", "allowed": ["unknown"]}
    if bad == "duplicate_skill":
        value["skills"] = {"mode": "manual", "allowed": ["academic-research"] * 2}
    if bad == "auto_allowed":
        value["skills"]["allowed"] = ["academic-research"]
    with pytest.raises(ValueError):
        config.resolve_selection(value)


def test_empty_manual_collection_blocks_all_skills(directory):
    with config.configuration_scope(
        config.resolve_selection(selection(directory, allowed=[]))
    ):
        assert skills_loader.format_skills_index() == "(当前没有可用 skill)"
        assert skills_loader.load_skill.invoke(
            {"skill_name": "academic-research"}
        ).startswith("错误：")


def test_two_async_requests_and_summary_threads_keep_separate_contexts(
    directory, monkeypatch
):
    snapshots = [
        config.resolve_selection(selection(directory, index, [name]))
        for index, name in enumerate(["academic-research", "product-comparison"])
    ]
    monkeypatch.setattr(
        config, "_defaults", {}
    )  # force construction of both archived revisions
    built = []

    def factory(**kwargs):
        built.append(kwargs)
        return SimpleNamespace(
            label=kwargs["model"],
            with_structured_output=lambda *a, **k: SimpleNamespace(
                invoke=lambda messages: SimpleNamespace(
                    summary=kwargs["model"], key_excerpts="fixture"
                )
            ),
        )

    monkeypatch.setattr(model_config, "init_chat_model", factory)

    async def run(snapshot):
        with config.configuration_scope(snapshot):
            await asyncio.sleep(0.01)
            labels = [config.selected_model(role, None).label for role in config.ROLES]
            sources = await asyncio.to_thread(
                utils.process_search_results,
                {
                    "a": {"title": "a", "raw_content": "text"},
                    "b": {"title": "b", "raw_content": "text"},
                },
            )
            return labels, sources, skills_loader.format_skills_index()

    async def both():
        return await asyncio.gather(*(run(snapshot) for snapshot in snapshots))

    results = asyncio.run(both())
    for index, (labels, sources, skills) in enumerate(results):
        assert labels == [f"fixture/{index}"] * 6
        assert all(
            f"fixture/{index}" in source["content"] for source in sources.values()
        )
        assert ("academic-research" in skills) == (index == 0)
        assert ("product-comparison" in skills) == (index == 1)
    assert len(built) == 12
    assert config.active_skills() is None


def test_model_binding_retry_and_shared_limiter(directory, monkeypatch):
    snapshot = config.resolve_selection(selection(directory))
    monkeypatch.setattr(config, "_defaults", {})
    factory = Mock(return_value=Mock())
    limiter = object()
    monkeypatch.setattr(model_config, "init_chat_model", factory)
    monkeypatch.setattr(model_config, "get_agent_rate_limiter", lambda: limiter)
    with config.configuration_scope(snapshot):
        config.selected_model("RESEARCHER", None, tools=["tool"])
        factory.return_value.bind_tools.assert_called_once_with(["tool"])
        assert factory.call_args.kwargs["rate_limiter"] is limiter
        config.selected_model("COMPRESSION", None, retry=True)
        factory.return_value.with_retry.assert_called_once_with(
            stop_after_attempt=3, wait_exponential_jitter=True
        )


def test_selection_and_snapshot_commit_with_intent_and_remain_immutable(
    directory, tmp_path
):
    journal = SubmissionJournal(tmp_path / "submissions.sqlite3")
    snapshot = config.resolve_selection(selection(directory))
    body = {
        "research_id": "research",
        "text": "Question",
        "expected_turn_id": None,
        "selection": snapshot["selection"],
    }
    first = journal.reserve("thread", "turn", body, snapshot)
    repeat = journal.reserve(
        "thread", "turn", body, config.resolve_selection(selection(directory, 1))
    )
    assert first["configuration"] == repeat["configuration"] == snapshot
    assert first["attempts"] == repeat["attempts"]
    with pytest.raises(SubmissionConflict):
        journal.reserve(
            "thread", "turn", {**body, "selection": selection(directory, 1)}, snapshot
        )
    changed = deepcopy(snapshot)
    changed["models"][0]["model"] = "other"
    with pytest.raises(SubmissionConflict):
        journal.enter_node(
            first["attempts"][0]["run_id"],
            "thread",
            "clarify_with_user",
            {"effective_config": changed},
        )


def test_qwen_fallback_uses_selected_model_transport(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://wrong.invalid")
    monkeypatch.setenv("LLM_API_KEY", "wrong")
    model = SimpleNamespace(
        openai_api_base="https://selected.invalid",
        openai_api_key=SimpleNamespace(get_secret_value=lambda: "selected-key"),
    )
    assert model_connection(model) == ("https://selected.invalid", "selected-key")


def test_qwen_summary_uses_shared_no_think_path(monkeypatch):
    model = SimpleNamespace(
        model_name="Qwen/test",
        openai_api_base="https://selected.invalid",
        openai_api_key=SimpleNamespace(get_secret_value=lambda: "selected-key"),
    )
    helper = Mock(
        return_value=SimpleNamespace(summary="summary", key_excerpts="excerpt")
    )
    monkeypatch.setattr(utils, "selected_model", lambda *args: model)
    monkeypatch.setattr(utils, "invoke_with_structured_output_fallback", helper)
    assert "summary" in utils.summarize_webpage_content("test")
    assert helper.call_args.args[0] is model
    assert helper.call_args.kwargs == {
        "base_url": "https://selected.invalid",
        "api_key": "selected-key",
    }


def test_direct_model_does_not_inherit_new_global_gateway(monkeypatch):
    from httpx import URL

    monkeypatch.setenv("LLM_BASE_URL", "https://new-global.invalid")
    model = SimpleNamespace(
        openai_api_base=None,
        root_client=SimpleNamespace(base_url=URL("https://api.openai.com/v1/")),
    )
    assert model_connection(model)[0] == "https://api.openai.com/v1/"


def test_clarification_preserves_snapshot_without_refreshing_defaults(
    directory, monkeypatch
):
    from langchain_core.messages import HumanMessage

    snapshot = config.resolve_selection(selection(directory))
    monkeypatch.setattr(full, "accepted_configuration", lambda: None)
    command = full.prepare_research(
        {
            "messages": [HumanMessage(content="answer", id="next")],
            "research_id": "r",
            "active_research_id": "r",
            "turn_id": "next",
            "active_turn_id": "previous",
            "research_status": "awaiting_input",
            "effective_config": snapshot,
        }
    )
    assert command.update["effective_config"] == snapshot
