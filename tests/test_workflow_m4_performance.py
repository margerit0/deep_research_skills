"""Opt-in local HTTP benchmark against the real v1 publication handler."""

import json
import math
import os
import time
from uuid import uuid4

import pytest

from tests.test_workflow_execution import document
from tests.test_workflow_execution_api import NativeFixture


class PerformanceFixture(NativeFixture):
    PARENT = ".local/graph-canvas-m4"


@pytest.mark.skipif(
    os.getenv("ATLAS_WORKFLOW_M4_PERF") != "1", reason="opt-in native benchmark"
)
def test_validate_and_publish_maximum_workflow():
    fixture = PerformanceFixture("M4 native publication benchmark")
    try:
        fixture.start()
        value = document(clarify=False, extensions=12)
        assert len(value.definition.nodes) == 30 and len(value.definition.edges) == 29
        warmup, sample_count = 3, 30
        samples = {"validate": [], "publish": []}
        for index in range(warmup + sample_count):
            draft = fixture.post(
                "/atlas/workflows",
                {
                    "name": f"M4 performance #{index + 1}",
                    "request_id": str(uuid4()),
                    "source": {
                        "kind": "import",
                        "document": value.model_dump(mode="json"),
                    },
                },
            )
            path = f"/atlas/workflows/{draft['workflow_id']}"
            for action in samples:
                body = {"expected_edit_version": draft["edit_version"]}
                if action == "publish":
                    body["request_id"] = str(uuid4())
                start = time.perf_counter()
                result = fixture.post(f"{path}/{action}", body)
                if index >= warmup:
                    samples[action].append((time.perf_counter() - start) * 1000)
                if action == "validate":
                    assert result["valid"], result["issues"]
                else:
                    assert result["revision_number"] == 1
                    assert len(result["document"]["definition"]["nodes"]) == 30
        p95 = {
            action: sorted(times)[math.ceil(0.95 * sample_count) - 1]
            for action, times in samples.items()
        }
        audit = fixture.get(fixture.IDENTITY)["audit"]
        (fixture.directory / "publication-timing.json").write_text(
            json.dumps(
                {
                    "nodes": 30,
                    "edges": 29,
                    "warmups": warmup,
                    "samples_per_operation": sample_count,
                    "elapsed_ms": samples,
                    "p95_ms": p95,
                    "fixture_audit_entries": len(audit),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        assert not audit
        assert max(p95.values()) <= 1000, p95
    finally:
        fixture.finish()
