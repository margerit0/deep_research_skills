"""Pure unit fixtures verify logic only; these are not evaluation experiments.

No fake research workflow, Chat invocation, candidate-generation call or batch
runner is executed. Network connections are forbidden in every test.
"""

import copy
import json
import socket
import sqlite3
import sys
from pathlib import Path

import pytest

from deep_research import run_configuration as config
from deep_research.skill_evolution import (
    POLICY,
    SKILL,
    Attempt,
    Budget,
    CandidateDraft,
    Decision,
    Diagnosis,
    Evidence,
    Feedback,
    Gates,
    Manifest,
    Statistics,
    check_evidence,
    constraint_violations,
    decide,
    make_candidate,
    revision,
    sha,
    skill_definition,
    validate_diagnosis,
)
from deep_research.skill_evolution_accounting import import_accounting
from deep_research.skill_evolution_models import (
    ClaimSupport,
    Location,
    SupportResponse,
    claim_units,
    validate_support,
)
from deep_research.skill_evolution_runner import (
    collect,
    implementation_versions,
    normalize_export,
    phase_arms,
    read_dataset,
    versions,
)
from deep_research.skill_evolution_store import (
    Store,
    promote,
    rollback,
    safe_error,
)
from deep_research.skill_evolution_trace import after_tool, before_tool, capture_tools
from scripts.research_agent.skill_evolution import main, parser


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("network forbidden in deterministic tests")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(config, "archive_path", lambda: None)
    monkeypatch.setattr(config, "_definitions", {})


@pytest.fixture
def parent():
    return Path("src/deep_research/skills/product-comparison.md").read_text(encoding="utf-8")


@pytest.fixture
def manifest(parent):
    definition = skill_definition(parent)
    parent_id = revision(definition)
    config.archive(parent_id, definition)
    model = {"kind": "model", "model": "unit-fixture", "provider": "openai", "max_tokens": 100,
             "key_env": "UNIT_TEST_UNUSED", "base_url": None, "temperature": 0.0}
    identifier = revision(model)
    config.archive(identifier, model)
    snapshot = {"configuration_version": 1,
                "selection": {"version": 1, "models": dict.fromkeys(config.ROLES, identifier),
                              "skills": {"mode": "manual", "allowed": [SKILL]}},
                "models": [{"role": role, "config_id": identifier, "model": "unit-fixture", "provider": "openai", "max_tokens": 100} for role in config.ROLES],
                "skill_revisions": {SKILL: parent_id}}
    return Manifest(experiment_id="unit-logic-only", parent_revision=parent_id, configuration=snapshot,
                    judge_revision=identifier, **implementation_versions(),
                    datasets={s: {"dataset_id": s, "version": "v1", "examples": {s: sha(s)}} for s in ("development", "selection", "final")},
                    budget=Budget(max_skill_chars=12000, max_output_chars=5000, max_tokens=10000,
                                  max_searches=3, max_seconds=100.0, max_failures=0, recursion_limit=20),
                    gates=Gates(coverage_gain=0.1, support_floor=0.8, max_regression=0.05))


def observation(manifest, parent):
    return Evidence(experiment_id=manifest.experiment_id, run_id="unit-observation", example_id="development",
                    split="development", dataset_id="development", dataset_version="v1", example_digest=sha("development"),
                    task="unit contract", user_requirements="", constraints={}, versions=versions(manifest),
                    skill_revision=manifest.parent_revision, skill_body=skill_definition(parent)["body"],
                    loaded_skills=[SKILL], trace_complete=True,
                    feedback=[Feedback(key="criteria_coverage_score", score=0.5)])


def diagnosis(evidence):
    return Diagnosis(evidence_digest=revision([evidence.model_dump()]), hypotheses=[{
        "id": "h1", "cause": "skill_content", "hypothesis": "unit hypothesis",
        "evidence_refs": [f"{evidence.run_id}/skill_body", f"{evidence.run_id}/feedback"],
        "counterevidence": ["could be execution"], "validation": ["check paired observations"],
    }])


def draft(parent):
    return CandidateDraft(hypothesis_id="h1", document=parent + "\n" + POLICY + "\n按相同维度记录各对象证据缺口。\n",
                          rationale="unit logic", expected_improvements=["coverage"], impact_scope=["methodology"])


def rows(manifest):
    return [Attempt(run_id=arm, example_id="selection", split="selection", arm=arm,
                    skill_revision=manifest.parent_revision, status="complete", violations=[], output_chars=100,
                    evidence=Evidence(experiment_id=manifest.experiment_id, run_id=arm, example_id="selection",
                                      split="selection", dataset_id="selection", dataset_version="v1", example_digest=sha("selection"),
                                      task="unit contract", user_requirements="", constraints={}, versions=versions(manifest), trace_complete=True),
                    statistics=Statistics(tokens=100, searches=1, seconds=1.0, failures=0),
                    feedback=[Feedback(key="criteria_coverage_score", score=coverage),
                              Feedback(key="citation_grounding_score", score=1.0),
                              Feedback(key="source_support_score", score=1.0)])
            for arm, coverage in (("baseline", 0.5), ("1", 0.7))]


@pytest.mark.parametrize("field,value", [("rounds", 2), ("candidates", 3), ("analysis_calls", 2), ("max_tokens", 0), ("max_seconds", float("nan"))])
def test_budget_validation(manifest, field, value):
    data = manifest.budget.model_dump()
    data[field] = value
    with pytest.raises(ValueError):
        Budget.model_validate(data)


@pytest.mark.parametrize("collision", ["id", "hash", "dataset"])
def test_split_isolation(manifest, collision):
    data = manifest.model_dump()
    selection = data["datasets"]["selection"]
    if collision == "id":
        selection["examples"] = {"development": sha("selection")}
    elif collision == "hash":
        selection["examples"] = {"selection": sha("development")}
    else:
        selection["dataset_id"] = "development"
    with pytest.raises(ValueError):
        Manifest.model_validate(data)


def test_evidence_identity_and_missing_fields(manifest, parent):
    evidence = observation(manifest, parent)
    check_evidence(manifest, evidence, "development")
    assert evidence.statistics.tokens is None
    with pytest.raises(ValueError):
        check_evidence(manifest, evidence, "selection")
    evidence.versions["judge"] = "wrong"
    with pytest.raises(ValueError):
        check_evidence(manifest, evidence, "development")


@pytest.mark.parametrize("missing", ["skill_body", "loaded_skills", "trace_complete", "feedback"])
def test_insufficient_evidence_cannot_blame_skill(manifest, parent, missing):
    evidence = observation(manifest, parent)
    setattr(evidence, missing, False if missing == "trace_complete" else [] if missing == "feedback" else None)
    with pytest.raises(ValueError):
        validate_diagnosis(diagnosis(evidence), [evidence])


def test_references_and_non_skill_diagnosis(manifest, parent):
    evidence = observation(manifest, parent)
    result = diagnosis(evidence)
    validate_diagnosis(result, [evidence])
    result.hypotheses[0].cause = "execution_noncompliance"
    with pytest.raises(ValueError):
        make_candidate(draft(parent), manifest, parent, result)
    result.hypotheses[0].evidence_refs = ["invented/path"]
    with pytest.raises(ValueError):
        validate_diagnosis(result, [evidence])


@pytest.mark.parametrize("change", ["name", "priority", "price", "url", "length", "metadata"])
def test_candidate_guards(manifest, parent, change):
    value = draft(parent)
    if change == "name":
        value.document = value.document.replace("name: product-comparison", "name: other")
    elif change == "priority":
        value.document = value.document.replace(POLICY, "")
    elif change == "price":
        value.document += "价格为 100 元"
    elif change == "url":
        value.document += " https://example.invalid/fact"
    elif change == "metadata":
        value.document = value.document.replace("description:", "other:")
    else:
        value.document += "x" * 13000
    with pytest.raises(ValueError):
        make_candidate(value, manifest, parent, diagnosis(observation(manifest, parent)))


def test_candidate_context_isolation_and_archive(manifest, parent):
    from deep_research.skills_loader import SKILLS_BODY, load_skill
    original = copy.deepcopy(manifest.configuration)
    body = SKILLS_BODY[SKILL]
    candidate = make_candidate(draft(parent), manifest, parent, diagnosis(observation(manifest, parent)))
    isolated = config.with_skill_revision(original, SKILL, skill_definition(candidate.document))
    with config.configuration_scope(isolated):
        assert POLICY in load_skill.invoke({"skill_name": SKILL})
        with config.configuration_scope(original):
            assert load_skill.invoke({"skill_name": SKILL}) == skill_definition(parent)["body"]
        assert POLICY in load_skill.invoke({"skill_name": SKILL})
    assert SKILLS_BODY[SKILL] == body
    assert original == manifest.configuration
    assert config.active_skills() is None


@pytest.mark.parametrize("problem,expected", [("none", "pass"), ("missing_feedback", "insufficient_evidence"), ("unknown_tokens", "insufficient_evidence"),
    ("infrastructure", "insufficient_evidence"), ("quality", "reject"), ("missing_run", "insufficient_evidence"),
    ("duplicate", "insufficient_evidence"), ("gain", "reject"), ("support", "reject"),
    ("regression", "reject"), ("constraint", "reject"), ("tokens", "reject"), ("length", "reject")])
def test_deterministic_gate_logic(manifest, problem, expected):
    attempts = rows(manifest)
    candidate = attempts[1]
    if problem == "missing_feedback":
        candidate.feedback.pop()
    elif problem == "unknown_tokens":
        candidate.statistics.tokens = None
    elif problem == "infrastructure":
        candidate.status = "infrastructure_failure"
    elif problem == "quality":
        candidate.status = "quality_failure"
    elif problem == "missing_run":
        attempts.pop()
    elif problem == "duplicate":
        attempts.append(candidate)
    elif problem == "gain":
        candidate.feedback[0].score = 0.55
    elif problem == "support":
        candidate.feedback[2].score = 0.7
    elif problem == "regression":
        candidate.feedback[1].score = 0.9
    elif problem == "constraint":
        candidate.violations = ["source_scope"]
    elif problem == "tokens":
        candidate.statistics.tokens = 10001
    elif problem == "length":
        candidate.output_chars = 5001
    assert decide(manifest, attempts, "1").status == expected


def test_user_constraint_checks():
    constraints = {"allowed_source_urls": ["https://example.invalid/a"], "required_skills": [SKILL], "max_output_chars": 3}
    assert constraint_violations(constraints, [{"url": "https://example.invalid/b"}], [], "long") == ["source_scope", "required_skills", "output_length"]
    assert constraint_violations(constraints, [{"url": "https://example.invalid/a#part"}], [SKILL], "ok") == []
    assert "source_scope" in constraint_violations(constraints, [], [SKILL], "引用 https://example.invalid/b")


def test_support_locations_do_not_imply_support():
    text = "Only applies when enabled."
    sources = [{"text": text, "start": 0, "end": len(text), "truncated": False, "body_sha256": sha(text), "url": "https://example.invalid"}]
    result = SupportResponse(claims=[ClaimSupport(unit=0, verdict="contradicted", reason="condition omitted",
                                                locations=[Location(source_index=0, start=0, end=len(text))])])
    feedback = validate_support(result, ["Always applies."], sources)
    assert feedback.score == 0
    assert feedback.value["claims"][0]["locations"][0]["excerpt"] == text
    result.claims[0].locations[0].end += 1
    with pytest.raises(ValueError):
        validate_support(result, ["Always applies."], sources)
    with pytest.raises(ValueError):
        validate_support(SupportResponse(claims=[]), ["missing"], sources)
    with pytest.raises(ValueError):
        claim_units("sentence\n" * 161)


def test_archive_and_local_replacement_rollback(tmp_path, manifest, parent, monkeypatch):
    store = Store(tmp_path / "ledger")
    store.initialize(manifest, parent)
    with pytest.raises(sqlite3.IntegrityError):
        store.put("manifest", manifest.model_dump())
    target = tmp_path / "product-comparison.md"
    target.write_text(parent, encoding="utf-8")
    candidate = make_candidate(draft(parent), manifest, parent, diagnosis(observation(manifest, parent)))
    # Isolate the filesystem transaction from scoring; no research batch is run.
    conclusion = Decision(status="pass", reasons=["unit transaction precondition"], pairs=[])
    store.put("frozen", {"candidate_id": "1", "revision": candidate.revision, "selection_decision": conclusion.model_dump()})
    monkeypatch.setattr("deep_research.skill_evolution_runner.compare", lambda *args: conclusion)
    promote(store, target, candidate.model_dump(), conclusion.model_dump())
    assert store.get("promotion_completed")["revision"] == candidate.revision
    assert config.archive(candidate.revision)["body"] == skill_definition(candidate.document)["body"]
    rollback(store, target)
    assert target.read_text(encoding="utf-8") == parent
    assert store.get("rollback_completed")["revision"] == manifest.parent_revision
    with pytest.raises(ValueError):
        rollback(store, target)


def test_collect_rejects_held_out_data(tmp_path, manifest, parent):
    store = Store(tmp_path)
    store.initialize(manifest, parent)
    evidence = observation(manifest, parent)
    evidence.split = "final"
    with pytest.raises(ValueError):
        collect(store, [evidence.model_dump()])
    assert "development_evidence" not in store.names()


def test_held_out_plan_requires_freeze(tmp_path, manifest, parent):
    store = Store(tmp_path)
    store.initialize(manifest, parent)
    assert phase_arms(store, "development") == [("baseline", parent)]
    with pytest.raises(ValueError):
        phase_arms(store, "final")
    with pytest.raises(ValueError):
        phase_arms(store, "selection")


def test_historical_export_keeps_missing_trace_unknown(manifest):
    inputs, reference = {"research_brief": "unit contract"}, {"criteria": ["unit contract"]}
    manifest.datasets["development"].examples["development"] = revision({"inputs": inputs, "reference_outputs": reference})
    payload = {"experiment": manifest.experiment_id, "filter": "all", "total_runs": 1, "items": [{
        "run_id": "historical-unit", "example_id": "development", "input_payload": inputs,
        "reference_outputs": reference, "judge_criteria_coverage": {"score": 0.0}, "agent_error": "untrusted exception"}]}
    result = normalize_export(manifest, payload)[0]
    assert result["skill_body"] is None and result["tools"] is None and not result["trace_complete"]
    assert all(v is None for v in result["versions"].values())
    assert "untrusted exception" not in json.dumps(result)
    payload["filter"] = "only_failures"
    with pytest.raises(ValueError):
        normalize_export(manifest, payload)


def test_dataset_exact_content(tmp_path, manifest):
    export = {"dataset_id": "selection", "version": "v1", "examples": [{"id": "selection", "inputs": {}, "reference_outputs": {"criteria": ["unit contract"]}}]}
    example = export["examples"][0]
    manifest.datasets["selection"].examples["selection"] = revision({"inputs": example["inputs"], "reference_outputs": example["reference_outputs"]})
    path = tmp_path / "input.json"
    path.write_text(json.dumps(export), encoding="utf-8")
    assert len(read_dataset(path, manifest, "selection")) == 1
    with pytest.raises(ValueError):
        read_dataset(path, manifest, "development")
    export["examples"][0]["reference_outputs"]["criteria"].append("changed")
    path.write_text(json.dumps(export), encoding="utf-8")
    with pytest.raises(ValueError):
        read_dataset(path, manifest, "selection")


def test_trace_excludes_thoughts_and_counts_failed_search(manifest):
    with capture_tools(manifest.budget) as trace:
        before_tool("think_tool", {"reflection": "private"})
        after_tool("think_tool", "private")
        before_tool("tavily_search", {"query": "unit"})
        after_tool("tavily_search", error=ValueError("never persist exception prose"))
        assert trace["searches"] == trace["failures"] == 1
        assert "private" not in json.dumps(trace["tools"])
        assert "never persist" not in json.dumps(trace["tools"])
        before_tool("tavily_search", {"query": "two"})
        before_tool("tavily_search", {"query": "three"})
        with pytest.raises(ValueError):
            before_tool("tavily_search", {"query": "four"})


def test_safe_errors_and_secret_guard(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIT_API_KEY", "unit-secret-do-not-persist")
    store = Store(tmp_path)
    with pytest.raises(ValueError):
        store.put("unsafe", {"output": "unit-secret-do-not-persist"})
    assert safe_error(ValueError("unit-secret-do-not-persist")) == {"category": "execution_error"}
    diagnostic = safe_error(ValueError("choices_type=NoneType, choices_len=n/a, base_url=unit-secret-do-not-persist"))
    assert diagnostic["choices_type"] == "NoneType" and diagnostic["choices_count"] is None
    assert "unit-secret" not in json.dumps(diagnostic)


def test_accounting_preserves_unknown_and_requires_provenance(tmp_path, manifest, parent):
    store = Store(tmp_path)
    store.initialize(manifest, parent)
    row = rows(manifest)[0]
    row.statistics.tokens = None
    store.put(f"result/{row.run_id}", row.model_dump())
    payload = {"run_id": row.run_id, "result_digest": revision(row.model_dump()), "source_artifact_sha256": sha("unit ledger"),
               "source_description": "unit", "attested_by": "unit", "includes_all_retries_and_judges": True,
               "requests": [{"request_id": "a", "kind": "model", "failed": True, "tokens": None},
                            {"request_id": "b", "kind": "search", "failed": False, "tokens": None}]}
    import_accounting(store, payload)
    stats = store.get(f"accounting/{row.run_id}")["statistics"]
    assert stats["tokens"] is None and stats["failures"] == 1
    assert store.get(f"result/{row.run_id}")["statistics"]["tokens"] is None


def test_cli_parsing_and_external_gate(tmp_path):
    assert parser().parse_args(["run", "--dir", str(tmp_path), "--split", "final", "--dataset", "test.json"]).split == "final"
    with pytest.raises(SystemExit) as stopped:
        main(["generate", "--dir", str(tmp_path)])
    assert stopped.value.code == 2
    assert not (tmp_path / "evolution.sqlite3").exists()
    assert "deep_research.research_agent_skills" not in sys.modules
