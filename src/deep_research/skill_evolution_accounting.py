"""Import operator-attested complete provider accounting without guessing costs.

SDK/raw-HTTP retries are not reliably exposed by graph callbacks. An external
provider/proxy ledger can close that gap, but its completeness is an explicit
operator attestation, not something these local records can prove.
"""

from pydantic import Field

from deep_research.skill_evolution import Contract, Digest, Name, Statistics, revision


class RequestUsage(Contract):
    """Include successful and failed model/search attempts in the ledger."""

    request_id: Name
    kind: str = Field(pattern="^(model|search|source_access)$")
    failed: bool
    tokens: int | None = Field(default=None, ge=0)


class Accounting(Contract):
    """Bind a complete provider export and operator attestation to one run."""

    run_id: Name
    result_digest: Digest
    source_artifact_sha256: Digest
    source_description: Name
    attested_by: Name
    includes_all_retries_and_judges: bool
    requests: list[RequestUsage] = Field(min_length=1)


def import_accounting(store, payload):
    """Retain the original unknown stats and append a single audited supplement."""
    record = Accounting.model_validate(payload)
    result = store.get(f"result/{record.run_id}")
    if revision(result) != record.result_digest:
        raise ValueError("accounting is for a different result")
    if "frozen" in store.names() and result["split"] != "final":
        raise ValueError("selection accounting is frozen")
    if len({r.request_id for r in record.requests}) != len(record.requests):
        raise ValueError("duplicate provider requests")
    if not record.includes_all_retries_and_judges:
        raise ValueError("incomplete accounting cannot fill unknown statistics")
    models = [r for r in record.requests if r.kind == "model"]
    tokens = sum(r.tokens for r in models) if models and all(r.tokens is not None for r in models) else None
    stats = Statistics.model_validate(result["statistics"])
    stats.tokens = tokens
    stats.failures = sum(r.failed for r in record.requests)
    # Search budget is physical requests when attested telemetry is available.
    searches = sum(r.kind == "search" for r in record.requests)
    if stats.searches is not None and searches < stats.searches:
        raise ValueError("accounting omitted an observed search invocation")
    stats.searches = searches
    store.put(f"accounting/{record.run_id}", {"provenance": record.model_dump(), "statistics": stats.model_dump()})
