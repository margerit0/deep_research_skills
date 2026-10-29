"""Pure unit fixtures verify logic only; these are not evaluation experiments.

No fake research workflow, Chat invocation, candidate-generation call or batch
runner is executed. Network connections are forbidden in every test.
"""

import copy
import json
import socket
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from pathlib import Path

import pytest

from deep_research import run_configuration as config
from deep_research import skill_evolution_runner as runner
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
    compare,
    freeze,
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
from deep_research.skill_evolution_trace import (
    after_tool,
    before_tool,
    capture_tools,
    retained_source_evidence,
)
from deep_research.source_evidence import (
    capture_source_evidence,
    record_source_evidence,
)
from scripts.research_agent import skill_evolution as cli
from scripts.research_agent.skill_evolution import main, parser

ARCHIVE_PATH = config.archive_path


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


def visible_observations(body):
    with capture_source_evidence() as sources:
        record_source_evidence("https://example.invalid/unit", {"raw_content": "unit source text"})
    return {"skill_body": body, "loaded_skills": [SKILL], "trace_complete": True,
            "tools": [{"name": "load_skill", "input": {"skill_name": SKILL}, "status": "complete", "output": body},
                      {"name": "tavily_search", "input": {"query": "unit"}, "status": "complete", "output": "unit tool output"}],
            "source_evidence": sources, "compressed_research": "unit contract"}


def observation(manifest, parent):
    return Evidence(experiment_id=manifest.experiment_id, run_id="unit-observation", example_id="development",
                    split="development", dataset_id="development", dataset_version="v1", example_digest=sha("development"),
                    task="unit contract", user_requirements="", constraints={}, versions=versions(manifest),
                    skill_revision=manifest.parent_revision, **visible_observations(skill_definition(parent)["body"]),
                    feedback=[Feedback(key="criteria_coverage_score", score=0.5,
                                       value={"individual_evaluations": [{"criteria": "unit dimension", "captured": False}]})])


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
                                      task="unit contract", user_requirements="", constraints={}, versions=versions(manifest),
                                      skill_revision=manifest.parent_revision,
                                      **visible_observations(config.archive(manifest.parent_revision)["body"])),
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


@pytest.mark.parametrize("missing", ["skill_body", "skill_revision", "loaded_skills", "trace_complete", "feedback",
                                     "tools", "source_evidence", "compressed_research"])
def test_insufficient_evidence_cannot_blame_skill(manifest, parent, missing):
    evidence = observation(manifest, parent)
    setattr(evidence, missing, False if missing == "trace_complete" else [] if missing == "feedback" else None)
    with pytest.raises(ValueError):
        validate_diagnosis(diagnosis(evidence), [evidence])


@pytest.mark.parametrize("problem", ["aggregate_only", "unfinished_tool", "unobserved_load", "wrong_body"])
def test_content_diagnosis_requires_observed_load_and_item_feedback(manifest, parent, problem):
    evidence = observation(manifest, parent)
    if problem == "aggregate_only":
        evidence.feedback[0].value = {}
    elif problem == "unfinished_tool":
        evidence.tools[-1]["status"] = "started"
    elif problem == "unobserved_load":
        evidence.tools.pop(0)
    else:
        evidence.tools[0]["output"] = "different methodology"
    with pytest.raises(ValueError):
        validate_diagnosis(diagnosis(evidence), [evidence])
    # Other attributions can still describe incomplete evidence.
    result = diagnosis(evidence)
    result.hypotheses[0].cause = "insufficient_or_mixed"
    validate_diagnosis(result, [evidence])


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


@pytest.mark.parametrize("arm_index", [0, 1])
@pytest.mark.parametrize("problem", ["not_loaded", "unobserved", "wrong_body", "wrong_revision", "failed_load"])
def test_gates_require_actual_matching_load_in_both_arms(manifest, arm_index, problem):
    attempts = rows(manifest)
    evidence = attempts[arm_index].evidence
    if problem == "not_loaded":
        evidence.loaded_skills = []
    elif problem == "unobserved":
        evidence.tools.pop(0)
    elif problem == "wrong_body":
        evidence.tools[0]["output"] = "different methodology"
    elif problem == "wrong_revision":
        evidence.skill_revision = sha("different revision")
    else:
        evidence.tools[0].update(status="failed", error={"category": "execution_error"})
    result = decide(manifest, attempts, "1")
    assert result.status == "insufficient_evidence"
    assert any("matching Skill load" in reason for reason in result.reasons)


def test_compare_and_freeze_reject_missing_candidate_load(tmp_path, manifest, parent):
    # Gate unit records only: no graph, model, batch runner or report is invoked.
    store = Store(tmp_path)
    store.initialize(manifest, parent)
    candidate = make_candidate(draft(parent), manifest, parent, diagnosis(observation(manifest, parent)))
    store.put("candidate/1", candidate.model_dump())
    attempts = rows(manifest)
    row = attempts[1]
    row.skill_revision = row.evidence.skill_revision = candidate.revision
    row.evidence.skill_body = skill_definition(candidate.document)["body"]
    row.evidence.loaded_skills = []
    row.evidence.tools.pop(0)
    for item in attempts:
        store.put(f"attempt/{item.run_id}", item.model_dump())
    assert compare(store, "1").status == "insufficient_evidence"
    with pytest.raises(ValueError, match="selection gates"):
        freeze(store, "1")
    assert "frozen" not in store.names()


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


@pytest.mark.parametrize("missing", ["tools", "source_evidence", "compressed_research"])
def test_collect_downgrades_unsubstantiated_completeness(tmp_path, manifest, parent, missing):
    store = Store(tmp_path)
    store.initialize(manifest, parent)
    evidence = observation(manifest, parent)
    setattr(evidence, missing, None)
    assert evidence.trace_complete
    collect(store, [evidence.model_dump()])
    saved = Evidence.model_validate(store.get("development_evidence")[0])
    assert not saved.trace_complete
    assert getattr(saved, missing) is None
    with pytest.raises(ValueError):
        validate_diagnosis(diagnosis(saved), [saved])


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


@pytest.mark.parametrize("failure_point", ["during_capture", "after_capture"])
def test_source_bodies_survive_exception_without_graph_output(tmp_path, manifest, failure_point):
    body = "unit original body that is absent from the tool summary"
    url = "https://example.invalid/retained"
    with pytest.raises(RuntimeError), capture_tools(manifest.budget) as trace:
        with capture_source_evidence() as captured:
            record_source_evidence(url, {"raw_content": body})
            if failure_point == "during_capture":
                raise RuntimeError("unit exceptional exit")
        assert captured[0]["text"] == body
        raise RuntimeError("unit exceptional exit")
    saved = retained_source_evidence(trace, {}, {"allowed_source_urls": [url]})
    assert saved[0]["text"] == body and saved[0]["body_sha256"] == sha(body)
    assert saved[0]["end"] == len(body)
    assert retained_source_evidence(trace, {}, {"allowed_source_urls": []}) == []
    assert retained_source_evidence(trace, {"source_evidence": saved}, {}) == saved
    store = Store(tmp_path)
    store.put("unit-retained-source", saved)
    assert store.get("unit-retained-source") == saved
    # Leaving the scope and later retrievals must not mutate the saved trace.
    with capture_source_evidence():
        record_source_evidence(url, {"raw_content": "later body"})
    assert trace["source_evidence"] == saved


def test_observer_preserves_nested_capture_and_execution_isolation(manifest):
    with capture_tools(manifest.budget) as outer_trace:
        with capture_source_evidence() as outer:
            record_source_evidence("https://example.invalid/outer", {"raw_content": "outer"})
            with capture_source_evidence() as inner:
                record_source_evidence("https://example.invalid/inner", {"raw_content": "inner"})
        with capture_tools(manifest.budget) as nested_trace:
            with capture_source_evidence():
                record_source_evidence("https://example.invalid/nested", {"raw_content": "nested"})
    assert [r["text"] for r in outer] == ["outer"]
    assert [r["text"] for r in inner] == ["inner"]
    assert [r["text"] for r in outer_trace["source_evidence"]] == ["outer", "inner"]
    assert [r["text"] for r in nested_trace["source_evidence"]] == ["nested"]

    def one(index):
        with capture_tools(manifest.budget) as trace:
            with capture_source_evidence():
                # Retrieval's summary workers inherit the caller's context.
                with ThreadPoolExecutor(max_workers=1) as workers:
                    workers.submit(copy_context().run, record_source_evidence,
                                   f"https://example.invalid/{index}", {"raw_content": str(index)}).result()
        return trace["source_evidence"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(one, [1, 2]))
    assert [r["text"] for r in first] == ["1"]
    assert [r["text"] for r in second] == ["2"]


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


@pytest.mark.parametrize("path_variable", ["ATLAS_CONFIG_DB", "ATLAS_SUBMISSION_DB"])
def test_cli_init_reads_environment_archive_with_empty_cache(tmp_path, manifest, parent, monkeypatch, path_variable):
    from deep_research import atlas_runtime

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "archive_path", ARCHIVE_PATH)
    monkeypatch.setattr(atlas_runtime, "compatible_runtime", lambda: True)
    monkeypatch.setenv("LANGGRAPH_RUNTIME_VARIANT", "inmem")
    monkeypatch.setenv("LANGGRAPH_DISABLE_FILE_PERSISTENCE", "false")
    monkeypatch.setenv("ATLAS_SUBMISSIONS_ENABLED", "true")
    monkeypatch.delenv("ATLAS_CONFIG_DB", raising=False)
    monkeypatch.delenv("ATLAS_SUBMISSION_DB", raising=False)
    configured_path = tmp_path / "custom" / "archive.sqlite3"
    monkeypatch.setenv(path_variable, str(configured_path))
    archive_file = config.archive_path()
    for identifier, definition in list(config._definitions.items()):
        config.archive(identifier, definition)
    assert archive_file.exists()
    # Separate CLI commands cannot rely on the preceding process's memory/env.
    config._definitions.clear()
    monkeypatch.delenv(path_variable)
    (tmp_path / ".env").write_text(f"{path_variable}='{configured_path.as_posix()}'\n", encoding="utf-8")
    environment_loader = cli.load_environment

    def load_test_environment():
        # Use a temporary backend .env without touching production configuration.
        with monkeypatch.context() as local:
            local.setattr(runner, "ROOT", tmp_path)
            environment_loader()

    monkeypatch.setattr(cli, "load_environment", load_test_environment)
    spec, document = tmp_path / "manifest.json", tmp_path / "product-comparison.md"
    spec.write_text(manifest.model_dump_json(), encoding="utf-8")
    document.write_text(parent, encoding="utf-8")
    directory = tmp_path / "experiment"
    assert main(["init", "--dir", str(directory), "--spec", str(spec), "--parent", str(document)]) == 0
    assert config.archive_path() == archive_file
    assert Store(directory).manifest == manifest
    assert not (tmp_path / ".langgraph_api").exists()
    assert "deep_research.research_agent_skills" not in sys.modules


def test_cli_help_and_denied_calls_do_not_load_environment(tmp_path, monkeypatch):
    def denied():
        raise AssertionError("environment must not be loaded")

    monkeypatch.setattr(cli, "load_environment", denied)
    with pytest.raises(SystemExit) as help_exit:
        main(["--help"])
    assert help_exit.value.code == 0
    with pytest.raises(SystemExit) as denied_exit:
        main(["run", "--dir", str(tmp_path), "--split", "development", "--dataset", "unused.json"])
    assert denied_exit.value.code == 2
