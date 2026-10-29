"""Explicit, bounded live entry points; never invoked by offline validation."""

import json
import time
import uuid
from pathlib import Path

from pydantic import Field

from deep_research.run_configuration import (
    archive,
    configuration_scope,
    revision,
    with_skill_revision,
)
from deep_research.skill_evolution import (
    SKILL,
    Attempt,
    Candidate,
    Contract,
    Diagnosis,
    Evidence,
    Feedback,
    Manifest,
    Statistics,
    check_evidence,
    constraint_violations,
    decide,
    make_candidate,
    sha,
    skill_definition,
    visible_evidence_complete,
)
from deep_research.skill_evolution_models import diagnose, evaluate_support, generate
from deep_research.skill_evolution_store import Store, safe_error, secret_check
from deep_research.skill_evolution_trace import capture_tools, retained_source_evidence

ROOT = Path(__file__).resolve().parents[2]


class Example(Contract):
    """Use existing inputs/reference criteria; never generate evaluation data."""

    id: str = Field(min_length=1)
    inputs: dict
    reference_outputs: dict


def implementation_versions() -> dict:
    """Pin implementation, prompts and evaluators by exact local file hashes."""
    source = ROOT / "src/deep_research"
    script = ROOT / "scripts/research_agent/run_research_eval.py"
    files = sorted(source.glob("*.py")) + [script, ROOT / "uv.lock"]
    return {
        "code_revision": revision({str(p.relative_to(ROOT)): sha(p.read_text(encoding="utf-8")) for p in files}),
        "prompt_revision": revision([sha((source / name).read_text(encoding="utf-8")) for name in ("prompts.py", "skill_evolution_models.py")]),
        "evaluator_revision": revision([sha(script.read_text(encoding="utf-8")), sha((source / "skill_evolution_models.py").read_text(encoding="utf-8"))]),
    }


def verify_implementation(manifest):
    """Refuse execution after code/prompts/evaluators have changed."""
    if any(getattr(manifest, key) != value for key, value in implementation_versions().items()):
        raise ValueError("implementation changed since manifest was sealed")


def versions(manifest):
    """Identify the public execution configuration without exposing endpoints."""
    return {"code": manifest.code_revision, "prompts": manifest.prompt_revision,
            "evaluators": manifest.evaluator_revision,
            "configuration": revision(manifest.configuration), "judge": manifest.judge_revision}


def load_environment():
    """Load only the repository backend .env, before importing graph modules."""
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")


def capture_configuration():
    """Archive existing role configuration without invoking any model."""
    load_environment()
    from deep_research.model_config import get_chat_model
    from deep_research.run_configuration import ROLES, register_model, resolve_selection
    from deep_research.structured_output_fallback import model_connection

    for role in ROLES:
        get_chat_model(role, max_tokens=32000 if role == "COMPRESSION" else None)
    snapshot = resolve_selection()
    model = get_chat_model("JUDGE")
    definition = {"kind": "model", "model": model.model_name if hasattr(model, "model_name") else model.model,
                  "provider": "anthropic" if "anthropic" in type(model).__module__ else "openai",
                  "max_tokens": model.max_tokens, "temperature": 0.0}
    # Reuse the same credential-name selection and archive format as all roles.
    register_model("JUDGE", definition, model_connection(model)[0])
    from deep_research.run_configuration import _defaults, _definitions

    identifier = _defaults["JUDGE"]
    archive(identifier, _definitions[identifier])
    return {"configuration": snapshot, "judge_revision": identifier, **implementation_versions()}


def judge_model(manifest):
    """Reconstruct the frozen judge through the existing model configuration."""
    from deep_research.run_configuration import selected_model

    snapshot = json.loads(json.dumps(manifest.configuration))
    # A judge is a read-only evaluator, isolated through an existing role slot.
    definition = archive(manifest.judge_revision)
    snapshot["selection"]["models"]["FINAL_REPORT"] = manifest.judge_revision
    snapshot["models"] = [m for m in snapshot["models"] if m["role"] != "FINAL_REPORT"] + [{
        "role": "FINAL_REPORT", "config_id": manifest.judge_revision,
        **{k: definition[k] for k in ("model", "provider", "max_tokens")},
    }]
    with configuration_scope(snapshot):
        return selected_model("FINAL_REPORT", None)


def collect(store: Store, items: list[dict]):
    """Normalize a full explicit development export; retain failed/missing rows."""
    manifest = store.manifest
    evidence = [Evidence.model_validate(item) for item in items]
    if not evidence or len({e.run_id for e in evidence}) != len(evidence):
        raise ValueError("empty evidence or duplicate run IDs")
    for item in evidence:
        check_evidence(manifest, item, "development", allow_unknown=True)
        if any(v is None for v in item.versions.values()) or not visible_evidence_complete(item):
            item.trace_complete = False
        if item.skill_revision is not None and item.skill_revision != manifest.parent_revision:
            raise ValueError("development evidence has wrong parent")
        if item.skill_body is not None and item.skill_body != skill_definition(store.get("parent"))["body"]:
            raise ValueError("development skill body mismatch")
    store.put("development_evidence", [e.model_dump() for e in evidence])


def normalize_export(manifest: Manifest, payload: dict) -> list[dict]:
    """Adapt explicit fetch exports without inventing historical trace/version data."""
    if payload.get("experiment") != manifest.experiment_id or payload.get("filter") != "all":
        raise ValueError("explicit matching, unfiltered experiment export required")
    result = []
    dataset = manifest.datasets["development"]
    for item in payload["items"]:
        if not item.get("input_payload") or not item.get("reference_outputs"):
            raise ValueError("export lacks exact input/reference identity; fetch again explicitly")
        digest = revision({"inputs": item["input_payload"], "reference_outputs": item["reference_outputs"]})
        feedback = []
        for source, key, fields in (
            ("judge_criteria_coverage", "criteria_coverage_score", ("individual_evaluations",)),
            ("judge_citation_grounding", "citation_grounding_score", ("has_sources_section", "claims")),
        ):
            value = item.get(source, {})
            feedback.append(Feedback(key=key, score=value.get("score"), comment=value.get("summary") or "",
                                     value={k: value.get(k) for k in fields}).model_dump())
        result.append(Evidence(
            experiment_id=manifest.experiment_id, run_id=item["run_id"], example_id=item["example_id"],
            split="development", dataset_id=dataset.dataset_id, dataset_version=dataset.version,
            example_digest=digest, task=item.get("input_research_brief", ""),
            user_requirements=item["input_payload"].get("user_requirements", ""),
            constraints=item["input_payload"].get("research_constraints", {}),
            source_evidence=item.get("source_evidence"), compressed_research=item.get("agent_compressed_research"),
            errors=[{"category": "historical_run_error"}] if item.get("agent_error") else [],
            feedback=feedback, versions=dict.fromkeys(versions(manifest)), trace_complete=False,
        ).model_dump())
    if payload.get("total_runs") != len(result):
        raise ValueError("export missing runs")
    return result


def analysis(store: Store):
    """Reserve the single diagnosis call before constructing or invoking a model."""
    manifest = store.manifest
    verify_implementation(manifest)
    evidence = [Evidence.model_validate(e) for e in store.get("development_evidence")]
    store.put("analysis_started", {"evidence_digest": revision([e.model_dump() for e in evidence])})
    load_environment()
    try:
        result = diagnose(judge_model(manifest), evidence)
        store.put("diagnosis", result.model_dump())
    except Exception as exc:
        store.put("analysis_failed", safe_error(exc))
        raise


def candidates(store: Store):
    """Generate at most two candidates once; keep invalid attempts and diagnostics."""
    manifest = store.manifest
    verify_implementation(manifest)
    diagnosis = Diagnosis.model_validate(store.get("diagnosis"))
    evidence = [Evidence.model_validate(e) for e in store.get("development_evidence")]
    store.put("generation_started", {"round": 1, "diagnosis": revision(diagnosis.model_dump())})
    load_environment()
    try:
        drafts = generate(judge_model(manifest), diagnosis, store.get("parent"), evidence, manifest.budget.candidates)
        store.put("drafts", drafts.model_dump())
        for index, draft in enumerate(drafts.candidates):
            try:
                candidate = make_candidate(draft, manifest, store.get("parent"), diagnosis)
                # Reject copied answer/criterion lines even when they contain no numbers.
                added = {line[1:].strip() for line in candidate.diff.splitlines() if line.startswith("+")}
                forbidden = {line.strip() for e in evidence for line in (e.compressed_research or "").splitlines() if len(line.strip()) >= 16}
                forbidden.update(str(row.get("criteria", "")).strip() for e in evidence for f in e.feedback
                                 for row in f.value.get("individual_evaluations", []) if len(str(row.get("criteria", ""))) >= 16)
                if any(answer in line for answer in forbidden for line in added):
                    raise ValueError("candidate copies development answer/criterion")
                store.put(f"candidate/{index + 1}", candidate.model_dump())
            except ValueError as exc:
                store.put(f"candidate_rejected/{index + 1}", safe_error(exc))
    except Exception as exc:
        store.put("generation_failed", safe_error(exc))
        raise


def read_dataset(path: Path, manifest: Manifest, split: str) -> list[Example]:
    """Read only the explicitly requested split and verify all content hashes."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if set(payload) != {"dataset_id", "version", "examples"}:
        raise ValueError("invalid dataset export")
    dataset = manifest.datasets[split]
    if payload["dataset_id"] != dataset.dataset_id or payload["version"] != dataset.version:
        raise ValueError("dataset identity mismatch")
    examples = [Example.model_validate(e) for e in payload["examples"]]
    actual = {e.id: revision({"inputs": e.inputs, "reference_outputs": e.reference_outputs}) for e in examples}
    if len(actual) != len(examples) or actual != dataset.examples:
        raise ValueError("dataset membership/content changed")
    for e in examples:
        if not e.reference_outputs.get("criteria") or not isinstance(e.reference_outputs["criteria"], list):
            raise ValueError("existing per-item criteria required")
        if set(e.inputs) - {"researcher_messages", "research_topic", "research_brief", "user_requirements", "research_constraints"}:
            raise ValueError("unsupported evaluation inputs")
    secret_check(payload)
    return examples


def attempts(store: Store) -> list[Attempt]:
    """Prefer completed records but retain every interrupted reservation."""
    result = []
    for name in store.names("attempt/"):
        end = name.replace("attempt/", "result/", 1)
        row = Attempt.model_validate(store.get(end if end in store.names() else name))
        accounting = f"accounting/{row.run_id}"
        if accounting in store.names():
            row.statistics = Statistics.model_validate(store.get(accounting)["statistics"])
        result.append(row)
    return result


def compare(store: Store, candidate_id: str, split="selection"):
    """Recompute conclusions from immutable attempts, without automatic promotion."""
    candidate = store.get(f"candidate/{candidate_id}")
    manifest = store.manifest
    rows = attempts(store)
    for row in rows:
        if row.split != split or row.arm not in {"baseline", candidate_id}:
            continue
        expected = manifest.parent_revision if row.arm == "baseline" else candidate["revision"]
        if row.skill_revision != expected or row.example_id not in manifest.datasets[split].examples:
            raise ValueError("attempt revision/example mismatch")
        if row.evidence:
            check_evidence(manifest, row.evidence, split)
            if row.evidence.run_id != row.run_id or row.evidence.skill_revision != expected:
                raise ValueError("attempt evidence mismatch")
            document = store.get("parent") if row.arm == "baseline" else candidate["document"]
            if row.evidence.skill_body != skill_definition(document)["body"]:
                raise ValueError("attempt Skill body mismatch")
    return decide(manifest, rows, candidate_id, split)


def freeze(store: Store, candidate_id: str):
    """Freeze one selection winner before any final data can be read."""
    decision = compare(store, candidate_id)
    if decision.status != "pass":
        raise ValueError("selection gates did not pass")
    store.put("frozen", {"candidate_id": candidate_id, "revision": store.get(f"candidate/{candidate_id}")["revision"],
                         "selection_decision": decision.model_dump()})


def phase_arms(store: Store, split: str):
    """Resolve permitted arms before any held-out data is opened."""
    if split == "development":
        arms = [("baseline", store.get("parent"))]
    elif split == "selection":
        if "frozen" in store.names():
            raise ValueError("selection is closed after freeze")
        arms = [("baseline", store.get("parent"))] + [(name.split("/")[1], store.get(name)["document"]) for name in store.names("candidate/")]
        if len(arms) == 1:
            raise ValueError("no validated candidates")
    elif split == "final":
        frozen = store.get("frozen")  # before opening final data
        arms = [("baseline", store.get("parent")), (frozen["candidate_id"], store.get(f"candidate/{frozen['candidate_id']}")["document"])]
    else:
        raise ValueError("unknown dataset split")
    return arms


def evaluate(store: Store, split: str, dataset_path: Path):
    """Run one registered paired batch, sequentially, with no whole-run retries."""
    manifest = store.manifest
    verify_implementation(manifest)
    arms = phase_arms(store, split)
    examples = read_dataset(dataset_path, manifest, split)
    store.put(f"batch/{split}", {"examples": [e.id for e in examples], "arms": [a for a, _ in arms]})
    load_environment()
    from deep_research.research_agent_skills import researcher_agent_skills
    from deep_research.research_requirements import constraints_for
    from deep_research.structured_output_fallback import (
        invoke_with_structured_output_fallback,
    )
    from scripts.research_agent.run_research_eval import (
        evaluate_citation_grounding,
        evaluate_criteria_coverage,
    )

    judge = judge_model(manifest)
    for index, example in enumerate(examples):
        # Alternate order to reduce a fixed baseline-first ordering effect.
        for arm, document in (arms if index % 2 == 0 else list(reversed(arms))):
            run_id = str(uuid.uuid4())
            definition = skill_definition(document)
            record = Attempt(run_id=run_id, example_id=example.id, split=split, arm=arm,
                             skill_revision=revision(definition), status="running")
            store.put(f"attempt/{run_id}", record.model_dump())
            start = time.monotonic()
            output, feedback, error = {}, [], None
            inputs = dict(example.inputs)
            from langchain_core.messages import convert_to_messages
            inputs["researcher_messages"] = convert_to_messages(inputs.get("researcher_messages", []))
            # Existing parsing/runtime precedence remains authoritative.
            constraints = constraints_for({k: v for k, v in inputs.items() if k != "research_constraints"})
            if "research_constraints" in inputs and inputs["research_constraints"] != constraints:
                raise ValueError("registered constraints differ from original user requirements")
            inputs["research_constraints"] = constraints
            with capture_tools(manifest.budget) as trace:
                try:
                    snapshot = with_skill_revision(manifest.configuration, SKILL, definition)
                    with configuration_scope(snapshot):
                        output = researcher_agent_skills.invoke(inputs, config={
                            "run_id": uuid.UUID(run_id), "recursion_limit": manifest.budget.recursion_limit,
                            "metadata": {"experiment_id": manifest.experiment_id, "example_id": example.id, "split": split, "arm": arm},
                        })
                    record.status = "quality_failure" if not output.get("compressed_research") or "研究未完成" in output["compressed_research"] or output.get("research_errors") else "complete"
                except Exception as exc:
                    error = safe_error(exc)
                    record.status = "quality_failure" if error.get("validation_reason") in {
                        "search budget exhausted", "execution time budget exhausted"
                    } else "infrastructure_failure"
                # Missing feedback is retained separately from target quality/infra failure.
                if record.status != "infrastructure_failure":
                    for evaluate_one in (
                        lambda: evaluate_criteria_coverage(output, example.reference_outputs, judge=judge, invoke=invoke_with_structured_output_fallback),
                        lambda: evaluate_citation_grounding(output, judge=judge, invoke=invoke_with_structured_output_fallback),
                        lambda: evaluate_support(judge, output.get("compressed_research", ""), output.get("source_evidence", [])),
                    ):
                        if time.monotonic() - start > manifest.budget.max_seconds:
                            error = {"category": "time_budget_exhausted"}
                            break
                        try:
                            value = evaluate_one()
                            feedback.append(value if isinstance(value, Feedback) else Feedback.model_validate(value))
                        except Exception as exc:
                            trace["failures"] += 1
                            error = safe_error(exc)
            record.feedback = feedback
            record.error = error
            # Raw fallback/SDK retries have no complete usage ledger yet. Never use 0.
            record.statistics = Statistics(searches=trace["searches"], seconds=time.monotonic() - start,
                                           failures=None, tokens=None)
            text = output.get("compressed_research", "")
            sources = retained_source_evidence(trace, output, constraints)
            record.output_chars = len(text)
            record.violations = constraint_violations(constraints, output.get("sources", []) + sources, trace["loaded"], text)
            dataset = manifest.datasets[split]
            record.evidence = Evidence(
                experiment_id=manifest.experiment_id, run_id=run_id, example_id=example.id, split=split,
                dataset_id=dataset.dataset_id, dataset_version=dataset.version, example_digest=dataset.examples[example.id],
                task=inputs.get("research_topic") or inputs.get("research_brief") or "\n".join(str(m.content) for m in inputs["researcher_messages"] if m.type == "human"),
                user_requirements=inputs.get("user_requirements", ""), constraints=constraints,
                skill_revision=revision(definition), skill_body=definition["body"], loaded_skills=trace["loaded"],
                tools=trace["tools"], source_evidence=sources, compressed_research=text,
                errors=([error] if error else []) + [{"category": "research_failure"} for _ in output.get("research_errors", [])],
                feedback=feedback, versions=versions(manifest), statistics=record.statistics,
                trace_complete=record.status != "infrastructure_failure" and bool(output),
            )
            store.put(f"result/{run_id}", record.model_dump())
    if split == "development":
        collect(store, [a.evidence.model_dump() for a in attempts(store) if a.split == split and a.evidence is not None])


def report(store: Store) -> str:
    """Render evidence → hypotheses → diffs → item results → gate reasons."""
    manifest = store.manifest
    lines = [f"# Skill evolution: {manifest.experiment_id}", "",
             "评估对象是 compressed_research；不能解释为 final_report 质量。模型归因为待验证假设。",
             "未运行或缺失的数据保持未知；本报告不宣称分数改善或真实端到端验收。", "",
             "## Manifest", "```json", json.dumps(manifest.model_dump(), ensure_ascii=False, indent=2), "```"]
    for name in ("development_evidence", "diagnosis", "analysis_failed", "generation_failed", "drafts"):
        if name in store.names():
            lines += [f"\n## {name}", "```json", json.dumps(store.get(name), ensure_ascii=False, indent=2), "```"]
    for name in store.names("candidate/"):
        candidate = Candidate.model_validate(store.get(name))
        candidate_id = name.split("/")[1]
        lines += [f"\n## {name}", candidate.rationale, "```diff", candidate.diff, "```"]
        for split in ("selection", "final"):
            decision = compare(store, candidate_id, split)
            lines += [f"### {split}: {decision.status}", "```json", decision.model_dump_json(indent=2), "```"]
    lines += ["\n## All attempts (including incomplete/failures)"]
    for item in attempts(store):
        lines += ["```json", item.model_dump_json(indent=2), "```"]
    lines += ["\n## Lifecycle", "```json", json.dumps({name: store.get(name) for name in store.names()
              if name in {"frozen", "promotion", "promotion_completed", "rollback", "rollback_completed"}
              or name.startswith(("candidate_rejected/", "command_failed/", "batch/", "accounting/"))}, ensure_ascii=False, indent=2), "```"]
    return "\n".join(lines) + "\n"
