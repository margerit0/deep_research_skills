"""Opt-in visible tool capture and search limits, inert in production runs."""

from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic

from deep_research.skill_evolution_store import safe_error, secret_check
from deep_research.source_evidence import merge_source_evidence, observe_source_evidence

_capture = ContextVar("skill_evolution_capture", default=None)


@contextmanager
def capture_tools(budget):
    """Capture only search/load observations, excluding think_tool content."""
    trace = {"tools": [], "loaded": [], "searches": 0, "failures": 0,
             "budget": budget, "started": monotonic()}
    token = _capture.set(trace)
    try:
        with observe_source_evidence() as sources:
            trace["source_evidence"] = sources
            yield trace
    finally:
        _capture.reset(token)


def retained_source_evidence(trace, output, constraints):
    """Merge captured source bodies even when the graph never returned output."""
    from deep_research.research_requirements import allowed_sources

    records = trace["source_evidence"] + (output.get("source_evidence") or [])
    sources = allowed_sources([{"url": item["url"]} for item in records], constraints)
    return merge_source_evidence(records, sources=sources)


def before_tool(name, args):
    """Reserve each search before invoking the tool, including failed searches."""
    trace = _capture.get()
    if trace is None:
        return
    if monotonic() - trace["started"] > trace["budget"].max_seconds:
        raise ValueError("execution time budget exhausted")
    if name == "tavily_search":
        if trace["searches"] >= trace["budget"].max_searches:
            raise ValueError("search budget exhausted")
        trace["searches"] += 1
    if name in {"tavily_search", "load_skill"}:
        safe = {k: args[k] for k in ("query", "skill_name") if k in args}
        secret_check(safe)
        trace["tools"].append({"name": name, "input": safe, "status": "started"})


def after_tool(name, result=None, audit=None, error=None):
    """Keep tool results and source decisions, never AI thoughts or reasoning."""
    trace = _capture.get()
    if trace is None:
        return
    if error is not None:
        trace["failures"] += 1
    if name not in {"tavily_search", "load_skill"}:
        return
    record = trace["tools"][-1]
    if error is not None:
        record.update(status="failed", error=safe_error(error))
    else:
        secret_check({"output": str(result), "source_audit": audit})
        record.update(status="complete", output=str(result), source_audit=audit or [])
        if name == "load_skill" and not str(result).startswith("错误："):
            trace["loaded"].append(record["input"]["skill_name"])
