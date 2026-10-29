"""Append-only local experiment ledger and explicit filesystem promotion."""

import json
import os
import re
import sqlite3
import tempfile
from pathlib import Path

from deep_research.run_configuration import archive, revision
from deep_research.skill_evolution import Manifest, skill_definition


def safe_error(exc: Exception) -> dict:
    """Keep shared safe fallback diagnostics, never exception/provider prose."""
    from deep_research.review_diagnostics import safe_provider_error

    result = {"category": "execution_error"}
    diagnostic = getattr(exc, "diagnostics", {})
    if isinstance(diagnostic, dict):
        for key in ("response_sha256", "response_characters", "finish_reason", "payload_type", "choices_type", "choices_count"):
            if key not in diagnostic:
                continue
            value = diagnostic.get(key)
            if isinstance(value, int) or value in (None, "stop", "length", "null", "list", "dict"):
                result[key] = value
            elif key == "response_sha256" and isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value):
                result[key] = value
        if "provider_error" in diagnostic:
            result["provider_error"] = safe_provider_error(diagnostic["provider_error"])
        if diagnostic.get("reason") in {"provider_error", "invalid_event", "invalid_choices", "invalid_delta", "incomplete_response", "schema_validation"}:
            result["reason"] = diagnostic["reason"]
        for key in ("done_marker", "schema_valid"):
            if type(diagnostic.get(key)) is bool:
                result[key] = diagnostic[key]
    if str(exc) in {
        "invalid frontmatter or skill length", "invalid skill name/description",
        "unsupported metadata or empty body", "candidate requires a skill-content hypothesis",
        "parent or metadata changed", "user priority/source boundary removed",
        "added concrete URL/date/price: methodology only", "empty change",
        "candidate copies development answer/criterion", "candidate budget exceeded",
        "search budget exhausted", "execution time budget exhausted",
    }:
        result["validation_reason"] = str(exc)
    # Keep shared Qwen payload-shape diagnostics, never endpoint or raw prose.
    if match := re.search(r"choices_type=(NoneType|list|dict|str)(?:,|$)", str(exc)):
        result["choices_type"] = match[1]
    if match := re.search(r"choices_len=(n/a|\d{1,6})(?:,|$)", str(exc)):
        result["choices_count"] = None if match[1] == "n/a" else int(match[1])
    return result


def secret_check(value):
    """Reject known local credentials rather than writing them into artifacts."""
    text = json.dumps(value, ensure_ascii=False)
    for key, secret in os.environ.items():
        if any(part in key.upper() for part in ("API_KEY", "TOKEN", "PASSWORD", "SECRET")) and len(secret) >= 8 and secret in text:
            raise ValueError("artifact contains a local secret")


class Store:
    """Keep immutable records and reserve actions transactionally before calls."""

    def __init__(self, root: Path):
        """Open a local experiment ledger without loading models."""
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "evolution.sqlite3"
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS records (name TEXT PRIMARY KEY, digest TEXT NOT NULL, body TEXT NOT NULL)")

    def connect(self):
        """Open a durable single-writer transaction."""
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA synchronous=FULL")
        return db

    def put(self, name, value):
        """Insert exactly once; failures and interrupted reservations remain."""
        secret_check(value)
        with self.connect() as db:
            db.execute("INSERT INTO records VALUES (?, ?, ?)", (name, revision(value), json.dumps(value, ensure_ascii=False)))

    def get(self, name):
        """Read a record after verifying its content address."""
        with self.connect() as db:
            row = db.execute("SELECT digest, body FROM records WHERE name=?", (name,)).fetchone()
        if not row:
            raise ValueError(f"missing artifact: {name}")
        value = json.loads(row[1])
        if revision(value) != row[0]:
            raise ValueError("artifact hash mismatch")
        return value

    def names(self, prefix=""):
        """List explicit artifact names; never choose a latest experiment."""
        with self.connect() as db:
            return [r[0] for r in db.execute("SELECT name FROM records ORDER BY name") if r[0].startswith(prefix)]

    @property
    def manifest(self):
        """Return the sealed manifest, checking schema and hash on every read."""
        return Manifest.model_validate(self.get("manifest"))

    def initialize(self, manifest: Manifest, parent: str):
        """Seal the parent and manifest atomically; refuse directory reuse."""
        definition = skill_definition(parent)
        if revision(definition) != manifest.parent_revision:
            raise ValueError("parent revision mismatch")
        values = {"manifest": manifest.model_dump(), "parent": parent}
        secret_check(values)
        with self.connect() as db:
            if db.execute("SELECT count(*) FROM records").fetchone()[0]:
                raise ValueError("experiment directory already initialized")
            for name, value in values.items():
                db.execute("INSERT INTO records VALUES (?, ?, ?)", (name, revision(value), json.dumps(value, ensure_ascii=False)))
        archive(manifest.parent_revision, definition)


def replace_document(path: Path, document: str):
    """Atomically replace one explicitly selected production file."""
    descriptor, temporary = tempfile.mkstemp(prefix=".skill-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(document)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def promote(store: Store, path: Path, candidate: dict, decision: dict):
    """Promote only an explicitly passed frozen candidate; archive the old file."""
    if path.name != "product-comparison.md" or decision["status"] != "pass":
        raise ValueError("promotion requires pass and product-comparison.md")
    frozen = store.get("frozen")
    if frozen["revision"] != candidate["revision"] or frozen["selection_decision"]["status"] != "pass":
        raise ValueError("candidate not frozen")
    from deep_research.skill_evolution_runner import compare
    if compare(store, frozen["candidate_id"], "final").model_dump() != decision:
        raise ValueError("promotion conclusion does not match final results")
    original = path.read_text(encoding="utf-8")
    if revision(skill_definition(original)) != candidate["parent_revision"]:
        raise ValueError("production parent changed")
    if revision(skill_definition(candidate["document"])) != candidate["revision"]:
        raise ValueError("candidate revision mismatch")
    store.put("promotion", {"path": str(path.resolve()), "before": original, "after_revision": candidate["revision"],
                            "decision": decision, "candidate": candidate["revision"]})
    archive(candidate["revision"], skill_definition(candidate["document"]))
    replace_document(path, candidate["document"])
    store.put("promotion_completed", {"revision": candidate["revision"]})


def rollback(store: Store, path: Path):
    """Restore the archived predecessor, refusing unrelated production edits."""
    record = store.get("promotion")
    if str(path.resolve()) != record["path"] or revision(skill_definition(path.read_text(encoding="utf-8"))) != record["after_revision"]:
        raise ValueError("rollback target changed")
    store.put("rollback", {"from": record["after_revision"], "to": store.manifest.parent_revision})
    replace_document(path, record["before"])
    store.put("rollback_completed", {"revision": store.manifest.parent_revision})
