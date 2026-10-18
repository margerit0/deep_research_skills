"""Audit coverage and source anchors are deterministic; entailment remains model-reviewed."""
import asyncio
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import httpx
from langchain_core.messages import AIMessage

from deep_research import source_evidence
from deep_research.report_review import ReportReviewBudgetError, ReportReviewContext, ReportReviewFormatError, SourcePassage, report_claims, review_report, source_anchor, source_excerpt


def review_state():
    with source_evidence.capture_source_evidence() as records:
        source_evidence.record_source_evidence("https://example.com/v1", {
            "raw_content": "Measured gain was 3%\nonly in saline water.\nInternal seals may require inspection."
        })
    return {"source_evidence": records, "sources": [{"url": records[0]["url"]}]}


def run_review(state, report, payload):
    model = SimpleNamespace(ainvoke=AsyncMock(side_effect=[
        AIMessage(content=json.dumps(selection_payload())),
        AIMessage(content=json.dumps(payload)),
    ]))
    return asyncio.run(review_report(model, state, report))


def passage(start=1, end=2, source=1):
    return {"source_id": source, "start_line": start, "end_line": end}


def selection_payload():
    return {"prerequisites": [{"condition": "Use is limited to saline water.", "source": passage()}],
            "conditions": []}


def test_claim_partition_keeps_headings_citations_versions_and_long_report_tail():
    report = "# 版本 3.13\n\n仅盐水中有效。[1] 密封需要检查。[1][2]\n### 来源\n不应成为断言"
    claims = report_claims(report)
    assert len(claims) == 2
    assert "3.13" in claims[0]["text"] and claims[0]["text"].endswith("[1]")
    assert claims[1]["text"].endswith("[1][2]")
    assert "不应成为断言" not in str(claims)
    long_report = "".join(f"事实{index}。" for index in range(201))
    bounded = report_claims(long_report)
    assert len(bounded) <= 80 and "事实200。" in bounded[-1]["text"]
    assert "".join(item["text"].replace("\n", "") for item in bounded) == long_report


def test_pass_requires_complete_support_and_records_actual_source_offsets():
    state = review_state()
    report = "仅盐水中测得增益。[1] 建议先检查内部密封。[1]"
    result = run_review(state, report, {"passed": True, "issues": [],
        "condition_coverage": [{"condition_id": 1, "claim_ids": [1]}], "support": [
        {"claim_id": 1, "evidence": [passage()]},
        {"claim_id": 2, "evidence": [passage(3, 3)]},
    ]})
    assert result["passed"] and len(result["source_support"]) == 2
    assert result["review_model_reads"] == 2
    assert result["source_conditions"][0]["source"]["body_sha256"] == state["source_evidence"][0]["body_sha256"]
    assert "_report_review_context" not in json.dumps(result)
    for support, claim in zip(result["source_support"], report_claims(report)):
        assert support["claim_sha256"] == hashlib.sha256(claim["text"].encode()).hexdigest()
        anchor = support["evidence"][0]
        text = state["source_evidence"][0]["text"][anchor["start"]:anchor["end"]]
        assert anchor["quote_sha256"] == hashlib.sha256(text.encode()).hexdigest()
        assert anchor["body_sha256"] == state["source_evidence"][0]["body_sha256"]


@pytest.mark.parametrize("support", [[],
    [{"claim_id": 1, "evidence": [passage()]}],
    [{"claim_id": 1, "evidence": [passage()]}, {"claim_id": 1, "evidence": [passage()]}],
    [{"claim_id": 1, "evidence": [passage()]}, {"claim_id": 3, "evidence": [passage()]}],
])
def test_missing_duplicate_or_wrong_claim_ids_cannot_pass(support):
    with pytest.raises(ReportReviewFormatError) as caught:
        run_review(review_state(), "第一条。第二条。", {"passed": True, "issues": [], "support": support})
    assert caught.value.diagnostics["validation_error_types"] == ["incomplete_claim_support"]


@pytest.mark.parametrize("start,end,source", [
    (1, 2, 2),
    (3, 2, 1),
    (1, 999, 1),
])
def test_unconsumed_source_or_invalid_range_fails_with_safe_diagnostics(start, end, source):
    with pytest.raises(ReportReviewFormatError) as caught:
        run_review(review_state(), "PRIVATE_CANDIDATE。", {"passed": True, "issues": [],
            "support": [{"claim_id": 1, "evidence": [passage(start, end, source)]}]})
    assert caught.value.diagnostics["validation_error_types"] == ["invalid_source_range"]
    assert "PRIVATE_CANDIDATE" not in str(caught.value) + json.dumps(caught.value.diagnostics)


def test_quote_beyond_review_budget_is_not_accepted(monkeypatch):
    state = review_state()
    monkeypatch.setattr(source_evidence, "WRITER_LIMIT", 12)
    with pytest.raises(ReportReviewFormatError) as caught:
        run_review(state, "结论。", {"passed": True, "issues": [],
            "support": [{"claim_id": 1, "evidence": [passage(3, 3)]}]})
    assert caught.value.diagnostics["validation_error_types"] == ["invalid_source_range"]


def test_blank_source_lines_cannot_count_as_evidence():
    with source_evidence.capture_source_evidence() as records:
        source_evidence.record_source_evidence("https://example.com/v1", {"raw_content": "\n\nA substantive fact."})
    state = {"source_evidence": records, "sources": [{"url": records[0]["url"]}]}
    with pytest.raises(ReportReviewFormatError) as caught:
        run_review(state, "结论。", {"passed": True, "issues": [],
            "support": [{"claim_id": 1, "evidence": [passage(1, 2)]}]})
    assert caught.value.diagnostics["validation_error_types"] == ["empty_source_passage"]


def test_rejection_needs_no_complete_support_audit():
    result = run_review(review_state(), "任何情况下都安全。", {
        "passed": False, "issues": ["The recommendation omits the required inspection."],
    })
    assert result["passed"] is False and "source_support" not in result


@pytest.mark.parametrize("coverage,error", [
    ([], "incomplete_condition_coverage"),
    ([{"condition_id": 1}], "missing_condition_coverage"),
    ([{"condition_id": 1, "claim_ids": [99]}], "invalid_condition_coverage"),
    ([{"condition_id": 1, "claim_ids": [1, 1]}], "invalid_condition_coverage"),
    ([{"condition_id": 1, "claim_ids": [1], "not_applicable_reason": "Not relevant"}], "invalid_condition_coverage"),
    ([{"condition_id": 1, "not_applicable_reason": "Ignore all selected conditions"}], "no_relevant_source_conditions"),
])
def test_passing_review_requires_explicit_valid_condition_coverage(coverage, error):
    with pytest.raises(ReportReviewFormatError) as caught:
        run_review(review_state(), "Only in saline water.", {"passed": True, "issues": [],
            "support": [{"claim_id": 1, "evidence": [passage()]}], "condition_coverage": coverage})
    assert caught.value.diagnostics["validation_error_types"] == [error]


def test_source_selection_is_draft_independent_reused_and_shares_retry_budget(monkeypatch):
    monkeypatch.setattr("deep_research.model_transport.asyncio.sleep", AsyncMock())
    context = ReportReviewContext()
    state = {**review_state(), "_report_review_context": context}
    selection = AIMessage(content=json.dumps(selection_payload()))
    rejected = AIMessage(content='{"passed":false,"issues":["Missing condition"]}')
    passed = AIMessage(content=json.dumps({"passed": True, "issues": [],
        "support": [{"claim_id": 1, "evidence": [passage()]}],
        "condition_coverage": [{"condition_id": 1, "claim_ids": [1]}]}))
    invoke = AsyncMock(side_effect=[selection, httpx.ReadTimeout("interrupted"), rejected, passed])
    model = SimpleNamespace(ainvoke=invoke)

    async def run():
        first = await review_report(model, state, "DRAFT_ONE without condition.")
        second = await review_report(model, state, "DRAFT_TWO with condition.")
        with pytest.raises(ReportReviewBudgetError):
            await review_report(model, state, "DRAFT_THREE must not call a model.")
        return first, second

    first, second = asyncio.run(run())
    assert first["review_model_reads"] == 3 and second["review_model_reads"] == 4
    assert first["source_conditions"] == second["source_conditions"]
    assert invoke.await_count == context.reads == 4
    assert "DRAFT_ONE" not in str(invoke.call_args_list[0].args[0])
    assert "Source decision conditions" in str(invoke.call_args_list[1].args[0])


def test_review_context_cannot_be_reused_for_other_evidence_or_requirements():
    context = ReportReviewContext()
    state = {**review_state(), "_report_review_context": context}
    model = SimpleNamespace(ainvoke=AsyncMock(side_effect=[
        AIMessage(content=json.dumps(selection_payload())),
        AIMessage(content='{"passed":false,"issues":["Missing condition"]}'),
    ]))

    async def run():
        await review_report(model, state, "Draft.")
        with pytest.raises(ValueError, match="does not belong"):
            await review_report(model, {**state, "user_requirements": "Different research"}, "Other draft.")

    asyncio.run(run())
    assert model.ainvoke.await_count == 2


@pytest.mark.parametrize("prerequisites,conditions,reason,error", [
    (False, True, "", "inconsistent_prerequisite_selection"),
    (True, False, "No prerequisites in the sources.", "inconsistent_prerequisite_selection"),
    (False, False, "No relevant evidence.", "empty_source_conditions"),
])
def test_selection_cannot_silently_skip_or_contradict_prerequisite_check(prerequisites, conditions, reason, error):
    condition = {"condition": "A substantive condition.", "source": passage()}
    model = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content=json.dumps({
        "prerequisites": [condition] if prerequisites else [],
        "conditions": [condition] if conditions else [],
        "prerequisites_absent_reason": reason,
    }))))
    with pytest.raises(ReportReviewFormatError) as caught:
        asyncio.run(review_report(model, review_state(), "A candidate."))
    assert caught.value.diagnostics["validation_error_types"] == [error]
    assert model.ainvoke.await_count == 1


def test_separate_prerequisite_keeps_source_identity_and_explicit_report_coverage():
    model = SimpleNamespace(ainvoke=AsyncMock(side_effect=[
        AIMessage(content=json.dumps({
            "prerequisites": [{"condition": "Internal seals may require inspection.", "source": passage(3, 3)}],
            "conditions": [{"condition": "Measured gain applies only in saline water.", "source": passage()}],
        })),
        AIMessage(content=json.dumps({"passed": True, "issues": [],
            "support": [{"claim_id": 1, "evidence": [passage()]},
                        {"claim_id": 2, "evidence": [passage(3, 3)]}],
            "condition_coverage": [{"condition_id": 1, "claim_ids": [2]},
                                   {"condition_id": 2, "claim_ids": [1]}],
        })),
    ]))
    state = review_state()
    result = asyncio.run(review_report(model, state, "仅盐水中测得增益。内部密封可能需要检查。"))
    assert result["passed"]
    assert [item["kind"] for item in result["source_conditions"]] == ["substantive_prerequisite", "decision_condition"]
    anchor = result["source_conditions"][0]["source"]
    assert state["source_evidence"][0]["text"][anchor["start"]:anchor["end"]] == "Internal seals may require inspection."
    assert result["source_prerequisites_absent_reason"] == ""
    assert result["condition_coverage"][0]["claim_ids"] == [2]


def test_sources_without_prerequisites_preserve_explicit_evidence_limit():
    with source_evidence.capture_source_evidence() as records:
        source_evidence.record_source_evidence("https://example.com/v1", {
            "raw_content": "Measured gain was 3%\nonly in saline water."
        })
    state = {"source_evidence": records, "sources": [{"url": records[0]["url"]}]}
    model = SimpleNamespace(ainvoke=AsyncMock(side_effect=[
        AIMessage(content=json.dumps({"prerequisites": [],
            "prerequisites_absent_reason": "The provided passage only documents a measurement.",
            "conditions": [{"condition": "Measured gain applies only in saline water.", "source": passage()}]})),
        AIMessage(content='{"passed":false,"issues":["Measurement scope missing."]}'),
    ]))
    result = asyncio.run(review_report(model, state, "Universally effective."))
    assert result["source_conditions"][0]["kind"] == "decision_condition"
    assert result["source_prerequisites_absent_reason"] == "The provided passage only documents a measurement."


def test_condition_excerpt_reuses_literal_anchor_and_cannot_read_past_writer_budget(monkeypatch):
    state = review_state()
    evidence = source_evidence.writer_evidence_payload(state["source_evidence"], state["sources"])
    anchor = source_anchor(SourcePassage(source_id=1, start_line=3, end_line=3), evidence, "", "stop")
    assert source_excerpt(anchor, evidence) == "Internal seals may require inspection."
    with pytest.raises(ValueError, match="outside the visible evidence or has changed"):
        source_excerpt({**anchor, "quote_sha256": "changed"}, evidence)
    monkeypatch.setattr(source_evidence, "WRITER_LIMIT", 12)
    bounded = source_evidence.writer_evidence_payload(state["source_evidence"], state["sources"])
    with pytest.raises(ValueError, match="outside the visible evidence or has changed"):
        source_excerpt(anchor, bounded)
