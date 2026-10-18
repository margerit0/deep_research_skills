"""Deterministic provenance, bounds and isolation; no model quality claims."""
import asyncio
import hashlib
import json
from copy import deepcopy

from deep_research.source_evidence import (
    SOURCE_LIMIT, WRITER_LIMIT, capture_source_evidence, merge_source_evidence,
    record_source_evidence, writer_evidence_context,
)
from deep_research.submission_journal import state_digest


def capture(url, body, **extra):
    with capture_source_evidence() as records:
        record_source_evidence(url, {"title": "Trial", "raw_content": body, **extra})
    return records


def test_exact_source_binding_hash_offsets_and_versions():
    url = "https://example.com/v1/trial?sample=a"
    body = "The target was 20%. Measured gain was 8% only in saline water."
    records = capture(url, body, retrieval="specified_url")
    item = records[0]
    assert item["body_sha256"] == hashlib.sha256(body.encode()).hexdigest()
    assert item["text"] == body[item["start"]:item["end"]] == body
    assert item["retrieval"] == "specified_url" and not item["truncated"]
    assert not merge_source_evidence(records, sources=[{"url": url.replace("v1", "v2")}])
    assert not merge_source_evidence(records, sources=[{"url": url.replace("sample=a", "sample=b")}])
    second = capture(url, "A revised trial contradicts the first.")
    merged = merge_source_evidence(records, records, second, sources=[{"url": url}])
    assert len(merged) == 2


def test_source_and_writer_limits_mark_uncovered_text_without_mutating_evidence():
    records = []
    for index in range(3):
        records += capture(f"https://example.com/{index}", "测" * (SOURCE_LIMIT + 1))
    sources = [{"url": item["url"]} for item in records]
    original = deepcopy(records)
    assert all(item["truncated"] and item["end"] == SOURCE_LIMIT for item in records)
    context = writer_evidence_context(records, sources)
    payload = json.loads(context[context.index('{'):context.rindex('}') + 1])
    assert sum(len(item["text"]) for item in payload["sources"]) == WRITER_LIMIT
    assert payload["sources"][-1]["text"] == ""
    assert payload["sources"][-1]["end"] == 0
    assert payload["sources"][-1]["truncated"]
    assert records == original


def test_snippets_and_legacy_missing_sources_are_explicit():
    with capture_source_evidence() as records:
        record_source_evidence("https://example.com/snippet", {"content": "Only a snippet."})
    assert records[0]["body_kind"] == "snippet"
    context = writer_evidence_context([], [{"url": "https://example.com/legacy"}])
    assert '"missing_source_text": ["https://example.com/legacy"]' in context
    assert state_digest({"notes": ["old"]}) != state_digest({"notes": ["old"], "source_evidence": []})
    current = {"source_evidence": records}
    changed = deepcopy(current)
    changed["source_evidence"][0]["text"] = "Changed"
    assert state_digest(current) != state_digest(changed)


def test_concurrent_and_nested_captures_do_not_leak():
    async def one(index):
        with capture_source_evidence() as records:
            await asyncio.to_thread(record_source_evidence, f"https://example.com/{index}",
                                    {"raw_content": f"condition {index}"})
            with capture_source_evidence() as nested:
                record_source_evidence("https://example.com/nested", {"raw_content": "nested"})
            assert len(nested) == 1
        record_source_evidence("https://example.com/outside", {"raw_content": "outside"})
        return records

    async def both():
        return await asyncio.gather(one(1), one(2))

    first, second = asyncio.run(both())
    assert [item["text"] for item in first] == ["condition 1"]
    assert [item["text"] for item in second] == ["condition 2"]
