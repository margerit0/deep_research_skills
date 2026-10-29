"""Pure contracts and decisions for one bounded product-comparison revision.

Importing this module never constructs a model or contacts a service.
"""

from __future__ import annotations

import difflib
import hashlib
import re
from typing import Annotated, Literal

import frontmatter
from pydantic import BaseModel, ConfigDict, Field, model_validator

from deep_research.run_configuration import revision

Name = Annotated[str, Field(min_length=1, max_length=160)]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Score = Annotated[float, Field(ge=0, le=1)]
Split = Literal["development", "selection", "final"]
SKILL = "product-comparison"
POLICY = "用户约束优先；不得为查询模板、来源数量或交叉验证扩大用户限定的来源范围；无合规证据时明确说明。"


class Contract(BaseModel):
    """Reject unknown fields and coercion at every persisted boundary."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Dataset(Contract):
    """Register identities and content hashes, without held-out content."""

    dataset_id: Name
    version: Name
    examples: dict[Name, Digest] = Field(min_length=1)


class Budget(Contract):
    """Fix generation limits and per-arm acceptance budgets before execution."""

    rounds: Literal[1] = 1
    candidates: int = Field(default=2, ge=1, le=2)
    analysis_calls: Literal[1] = 1
    generation_calls: Literal[1] = 1
    max_skill_chars: int = Field(ge=200, le=30000)
    max_output_chars: int = Field(gt=0)
    max_tokens: int = Field(gt=0)
    max_searches: int = Field(ge=0)
    max_seconds: float = Field(gt=0)
    max_failures: int = Field(ge=0)
    recursion_limit: int = Field(ge=2, le=100)


class Gates(Contract):
    """Require explicit thresholds; never derive them from observed scores."""

    coverage_gain: float = Field(gt=0, le=1)
    support_floor: Score
    max_regression: Score


class Manifest(Contract):
    """Seal all identities, revisions, gates and budgets before any call."""

    version: Literal[1] = 1
    experiment_id: Name
    skill: Literal["product-comparison"] = SKILL
    parent_revision: Digest
    datasets: dict[Split, Dataset]
    configuration: dict
    judge_revision: Digest
    code_revision: Name
    prompt_revision: Digest
    evaluator_revision: Digest
    budget: Budget
    gates: Gates

    @model_validator(mode="after")
    def isolated(self):
        """Disallow shared IDs or identical examples across the three splits."""
        if set(self.datasets) != {"development", "selection", "final"}:
            raise ValueError("three explicit dataset splits required")
        ids, hashes, datasets = set(), set(), set()
        for item in self.datasets.values():
            if item.dataset_id in datasets or ids.intersection(item.examples) or hashes.intersection(item.examples.values()):
                raise ValueError("dataset leakage: overlapping identity or content")
            if len(set(item.examples.values())) != len(item.examples):
                raise ValueError("duplicate example content")
            datasets.add(item.dataset_id)
            ids.update(item.examples)
            hashes.update(item.examples.values())
        if self.configuration.get("skill_revisions", {}).get(SKILL) != self.parent_revision:
            raise ValueError("parent does not match frozen configuration")
        return self


class Feedback(Contract):
    """Preserve the existing score/comment/value feedback contract."""

    key: Name
    score: Score | None = None
    comment: str = ""
    value: dict = Field(default_factory=dict)


class Statistics(Contract):
    """Unknown usage must remain null, including provider-internal retries."""

    tokens: int | None = Field(default=None, ge=0)
    searches: int | None = Field(default=None, ge=0)
    seconds: float | None = Field(default=None, ge=0)
    failures: int | None = Field(default=None, ge=0)


class Evidence(Contract):
    """Store visible observations, never hidden reasoning or raw model traces."""

    experiment_id: Name
    run_id: Name
    example_id: Name
    split: Split
    dataset_id: Name
    dataset_version: Name
    example_digest: Digest
    task: str
    user_requirements: str
    constraints: dict
    skill_revision: Digest | None = None
    skill_body: str | None = None
    loaded_skills: list[str] | None = None
    tools: list[dict] | None = None
    source_evidence: list[dict] | None = None
    compressed_research: str | None = None
    errors: list[dict] = Field(default_factory=list)
    feedback: list[Feedback] = Field(default_factory=list)
    versions: dict[str, str | None]
    statistics: Statistics = Field(default_factory=Statistics)
    trace_complete: bool = False


Cause = Literal[
    "skill_content", "skill_selection_loading", "execution_noncompliance",
    "retrieval_access", "compression_writing_loss", "infrastructure",
    "evaluator", "insufficient_or_mixed",
]


class Hypothesis(Contract):
    """Treat model attribution as a falsifiable hypothesis, never a fact."""

    id: Name
    cause: Cause
    hypothesis: str = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    counterevidence: list[str] = Field(min_length=1)
    validation: list[str] = Field(min_length=1)


class Diagnosis(Contract):
    """Keep diagnosis bound to an immutable development evidence pack."""

    evidence_digest: Digest
    hypotheses: list[Hypothesis]
    status: Literal["unverified_hypotheses"] = "unverified_hypotheses"


class CandidateDraft(Contract):
    """Propose one methodology change for one supported hypothesis."""

    hypothesis_id: Name
    document: str
    rationale: str = Field(min_length=1)
    expected_improvements: list[str] = Field(min_length=1)
    impact_scope: list[str] = Field(min_length=1)


class Candidate(CandidateDraft):
    """Bind a validated draft to its parent and exact diff."""

    parent_revision: Digest
    revision: Digest
    diff: str
    diagnosis_digest: Digest


class Attempt(Contract):
    """Retain every arm, including incomplete and failed attempts."""

    run_id: Name
    example_id: Name
    split: Split
    arm: Name
    skill_revision: Digest
    status: Literal["running", "complete", "quality_failure", "infrastructure_failure"]
    evidence: Evidence | None = None
    feedback: list[Feedback] = Field(default_factory=list)
    violations: list[str] | None = None
    statistics: Statistics = Field(default_factory=Statistics)
    output_chars: int | None = Field(default=None, ge=0)
    error: dict | None = None


class Decision(Contract):
    """Produce a deterministic, explicitly non-promoting conclusion."""

    status: Literal["pass", "reject", "insufficient_evidence"]
    reasons: list[str]
    pairs: list[dict]


def sha(text: str) -> str:
    """Hash exact UTF-8 text."""
    return hashlib.sha256(text.encode()).hexdigest()


def skill_definition(document: str, limit: int = 30000) -> dict:
    """Validate frontmatter with the same metadata shape as skills_loader."""
    if not document.startswith("---\n") or not 100 <= len(document) <= limit:
        raise ValueError("invalid frontmatter or skill length")
    post = frontmatter.loads(document)
    if post.get("name") != SKILL or not isinstance(post.get("description"), str) or not post["description"].strip():
        raise ValueError("invalid skill name/description")
    if (set(post.metadata) - {"name", "description", "when_to_use"} or not post.content.strip()
            or not isinstance(post.get("when_to_use", ""), str)):
        raise ValueError("unsupported metadata or empty body")
    return {"kind": "skill", "metadata": {
        "name": SKILL, "description": post["description"],
        "when_to_use": post.get("when_to_use", "") or "",
    }, "body": post.content}


def check_evidence(manifest: Manifest, evidence: Evidence, split: Split, *, allow_unknown=False):
    """Verify identity, dataset membership and all frozen revisions."""
    dataset = manifest.datasets[split]
    if (evidence.experiment_id != manifest.experiment_id or evidence.split != split
            or evidence.dataset_id != dataset.dataset_id or evidence.dataset_version != dataset.version
            or dataset.examples.get(evidence.example_id) != evidence.example_digest):
        raise ValueError("evidence identity/split mismatch")
    expected = {"code": manifest.code_revision, "prompts": manifest.prompt_revision,
                "evaluators": manifest.evaluator_revision,
                "configuration": revision(manifest.configuration), "judge": manifest.judge_revision}
    if (set(evidence.versions) != set(expected) or any(value != evidence.versions[key]
            and not (allow_unknown and evidence.versions[key] is None) for key, value in expected.items())):
        raise ValueError("evidence versions mismatch")


def evidence_index(evidence: list[Evidence]) -> dict:
    """Expose bounded, explicit reference paths without model self-narration."""
    refs = {}
    for item in evidence:
        for field in ("task", "user_requirements", "constraints", "skill_body", "loaded_skills",
                      "tools", "source_evidence", "compressed_research", "errors", "feedback"):
            value = item.model_dump()[field]
            if value is not None:
                refs[f"{item.run_id}/{field}"] = value
    return refs


def visible_evidence_complete(evidence: Evidence | None) -> bool:
    """Check recorded observations instead of trusting the completeness flag."""
    if (evidence is None or not evidence.trace_complete or not evidence.tools
            or evidence.source_evidence is None or not evidence.compressed_research
            or not evidence.compressed_research.strip()):
        return False
    return all(
        isinstance(tool.get("input"), dict) and (
            tool.get("status") == "complete" and isinstance(tool.get("output"), str)
            or tool.get("status") == "failed" and isinstance(tool.get("error"), dict)
        ) for tool in evidence.tools
    )


def skill_loading_observed(evidence: Evidence | None) -> bool:
    """Require successful tool output matching the claimed Skill body."""
    if (evidence is None or not evidence.skill_revision or not evidence.skill_body
            or SKILL not in (evidence.loaded_skills or [])):
        return False
    loads = [tool for tool in evidence.tools or []
             if tool.get("name") == "load_skill" and tool.get("status") == "complete"
             and isinstance(tool.get("input"), dict) and tool["input"].get("skill_name") == SKILL]
    return bool(loads) and all(tool.get("output") == evidence.skill_body for tool in loads)


def has_item_failure(feedback: list[Feedback]) -> bool:
    """Require failed item details, not just an unexplained aggregate score."""
    for item in feedback:
        if item.score is None or item.score >= 1:
            continue
        if item.key == "criteria_coverage_score":
            details = item.value.get("individual_evaluations") or []
            if any(isinstance(row, dict) and row.get("captured") is False for row in details):
                return True
        elif item.key in {"citation_grounding_score", "source_support_score"}:
            details = item.value.get("claims") or []
            if any(isinstance(row, dict) and (
                row.get("is_grounded") is False or row.get("verdict") in {"contradicted", "insufficient"}
                or item.value.get("has_sources_section") is False
            ) for row in details):
                return True
    return False


def validate_diagnosis(diagnosis: Diagnosis, evidence: list[Evidence]):
    """Reject fabricated references and hypotheses lacking loaded Skill evidence."""
    if diagnosis.evidence_digest != revision([e.model_dump() for e in evidence]):
        raise ValueError("diagnosis evidence digest mismatch")
    refs = evidence_index(evidence)
    if len({h.id for h in diagnosis.hypotheses}) != len(diagnosis.hypotheses):
        raise ValueError("duplicate hypothesis")
    for hypothesis in diagnosis.hypotheses:
        if any(ref not in refs for ref in hypothesis.evidence_refs):
            raise ValueError("unknown evidence reference")
        if hypothesis.cause == "skill_content":
            supported = any(
                visible_evidence_complete(e) and skill_loading_observed(e)
                and f"{e.run_id}/skill_body" in hypothesis.evidence_refs
                and f"{e.run_id}/feedback" in hypothesis.evidence_refs
                and has_item_failure(e.feedback)
                for e in evidence
            )
            if not supported:
                raise ValueError("skill_content requires loaded body, failure feedback and trace")


def make_candidate(draft: CandidateDraft, manifest: Manifest, parent: str, diagnosis: Diagnosis) -> Candidate:
    """Keep metadata and priority immutable and reject added facts/answers."""
    if not any(h.id == draft.hypothesis_id and h.cause == "skill_content" for h in diagnosis.hypotheses):
        raise ValueError("candidate requires a skill-content hypothesis")
    old = skill_definition(parent)
    new = skill_definition(draft.document, manifest.budget.max_skill_chars)
    if revision(old) != manifest.parent_revision or old["metadata"] != new["metadata"]:
        raise ValueError("parent or metadata changed")
    # Existing explicit constraint sentences must survive; add a fixed policy too.
    protected = [line for line in old["body"].splitlines() if "用户" in line and any(w in line for w in ("范围", "优先", "限定"))]
    if POLICY not in new["body"] or any(line not in new["body"] for line in protected):
        raise ValueError("user priority/source boundary removed")
    delta = list(difflib.unified_diff(parent.splitlines(), draft.document.splitlines(), fromfile="parent", tofile="candidate", lineterm=""))
    added = "\n".join(line[1:] for line in delta if line.startswith("+") and not line.startswith("+++"))
    if re.search(r"https?://|[$¥€£]|\b\d{4}\b|\d+(?:\.\d+)?\s*(?:元|美元|USD|CNY)", added, re.I):
        raise ValueError("added concrete URL/date/price: methodology only")
    if new["body"] == old["body"]:
        raise ValueError("empty change")
    return Candidate(**draft.model_dump(), parent_revision=manifest.parent_revision,
                     revision=revision(new), diff="\n".join(delta), diagnosis_digest=revision(diagnosis.model_dump()))


def constraint_violations(constraints: dict, sources: list[dict], loaded: list[str], text: str) -> list[str]:
    """Check explicit exact-URL, required-Skill and registered length constraints."""
    from deep_research.research_requirements import extract_urls, normalized_url

    result = []
    allowed = constraints.get("allowed_source_urls")
    if allowed is not None:
        allowed = {normalized_url(url) for url in allowed}
        if None in allowed:
            raise ValueError("invalid source allowlist")
        used_urls = [s.get("url", "") for s in sources] + extract_urls(text)
        if any(normalized_url(url) not in allowed for url in used_urls):
            result.append("source_scope")
    if not set(constraints.get("required_skills", [])).issubset(loaded):
        result.append("required_skills")
    if constraints.get("max_output_chars") is not None and len(text) > constraints["max_output_chars"]:
        result.append("output_length")
    return result


def decide(manifest: Manifest, attempts: list[Attempt], candidate: str, split: Split = "selection") -> Decision:
    """Compare all registered pairs; missing/failed attempts cannot disappear."""
    unknown, rejected, pairs = [], [], []
    for example_id in manifest.datasets[split].examples:
        rows = []
        for arm in ("baseline", candidate):
            matches = [a for a in attempts if a.split == split and a.example_id == example_id and a.arm == arm]
            if len(matches) != 1:
                unknown.append(f"{example_id}/{arm}: expected exactly one attempt")
                continue
            row = matches[0]
            rows.append(row)
            if not visible_evidence_complete(row.evidence):
                unknown.append(f"{row.run_id}: missing complete visible evidence")
            if (not skill_loading_observed(row.evidence)
                    or row.evidence.skill_revision != row.skill_revision):
                unknown.append(f"{row.run_id}: missing matching Skill load evidence")
            if row.status in {"running", "infrastructure_failure"}:
                unknown.append(f"{row.run_id}: {row.status}")
            if row.status == "quality_failure":
                rejected.append(f"{row.run_id}: quality failure")
            if row.violations is None or row.output_chars is None:
                unknown.append(f"{row.run_id}: missing constraints/output")
            scores = [f.key for f in row.feedback if f.score is not None]
            for key in ("criteria_coverage_score", "citation_grounding_score", "source_support_score"):
                if scores.count(key) != 1:
                    unknown.append(f"{row.run_id}: missing/duplicate {key}")
            for metric in ("tokens", "searches", "seconds", "failures"):
                value = getattr(row.statistics, metric)
                if value is None:
                    unknown.append(f"{row.run_id}: unknown {metric}")
                elif value > getattr(manifest.budget, f"max_{metric}"):
                    rejected.append(f"{row.run_id}: {metric} budget exceeded")
            if row.output_chars is not None and row.output_chars > manifest.budget.max_output_chars:
                rejected.append(f"{row.run_id}: output length exceeded")
        if len(rows) != 2:
            continue
        base, cand = rows
        if set(cand.violations or []) - set(base.violations or []):
            rejected.append(f"{example_id}: new hard constraint violation")
        b = {f.key: f.score for f in base.feedback if f.score is not None}
        c = {f.key: f.score for f in cand.feedback if f.score is not None}
        pairs.append({"example_id": example_id, "baseline_run": base.run_id, "candidate_run": cand.run_id,
                      "baseline": b, "candidate": c})
        for key in set(b) & set(c):
            if b[key] - c[key] > manifest.gates.max_regression + 1e-12:
                rejected.append(f"{example_id}: {key} regression")
        if c.get("source_support_score", 0) < manifest.gates.support_floor:
            rejected.append(f"{example_id}: evidence support below floor")
    gains = [p["candidate"]["criteria_coverage_score"] - p["baseline"]["criteria_coverage_score"]
             for p in pairs if "criteria_coverage_score" in p["candidate"] and "criteria_coverage_score" in p["baseline"]]
    if len(gains) == len(manifest.datasets[split].examples) and sum(gains) / len(gains) + 1e-12 < manifest.gates.coverage_gain:
        rejected.append("mean paired coverage gain below predeclared threshold")
    # Incomplete scoring/runs takes precedence: do not mislabel infra as quality.
    status = "insufficient_evidence" if unknown else "reject" if rejected else "pass"
    return Decision(status=status, reasons=unknown + rejected or ["all predeclared gates passed"], pairs=pairs)
