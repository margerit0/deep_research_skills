"""Server-owned, immutable model/Skills revisions and per-execution context.

Only public revision IDs cross the HTTP boundary. Archived definitions contain
endpoint and credential *environment names*, never credentials. Retain this
archive with the submission/checkpoint databases when restarting the service.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from functools import wraps
import hashlib
import inspect
import json
import os
from pathlib import Path
import sqlite3
import threading

from pydantic import BaseModel, ConfigDict, Field

ROLES = (
    "SCOPING",
    "SUPERVISOR",
    "RESEARCHER",
    "SUMMARIZATION",
    "COMPRESSION",
    "FINAL_REPORT",
)
_definitions = {}
_defaults = {}
_models = {}
_lock = threading.RLock()
_active = ContextVar("atlas_configuration", default=None)


class ConfigurationError(ValueError):
    """Unknown, changed or unsupported configuration."""


class SkillsSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mode: str = Field(pattern="^(auto|manual)$")
    allowed: list[str] = Field(max_length=100)


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: int = Field(ge=1, le=1)
    models: dict[str, str]
    skills: SkillsSelection


def revision(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def archive_path():
    from deep_research.atlas_runtime import submissions_enabled

    if not submissions_enabled():
        return None
    submission = Path(
        os.getenv("ATLAS_SUBMISSION_DB") or ".langgraph_api/atlas-submissions.sqlite3"
    )
    return Path(
        os.getenv("ATLAS_CONFIG_DB") or submission.with_name("atlas-configs.sqlite3")
    )


def archive(identifier, definition=None):
    with _lock:
        path = archive_path()
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(path, timeout=10) as db:
                db.execute("PRAGMA synchronous=FULL")
                db.execute(
                    "CREATE TABLE IF NOT EXISTS configurations (id TEXT PRIMARY KEY, body TEXT NOT NULL)"
                )
                if definition is not None:
                    db.execute(
                        "INSERT OR IGNORE INTO configurations VALUES (?, ?)",
                        (identifier, json.dumps(definition, ensure_ascii=False)),
                    )
                else:
                    row = db.execute(
                        "SELECT body FROM configurations WHERE id=?", (identifier,)
                    ).fetchone()
                    if row:
                        definition = json.loads(row[0])
        if definition is None:
            definition = _definitions.get(identifier)
        if definition is None or revision(definition) != identifier:
            raise ConfigurationError("configuration_revision_unavailable")
        _definitions[identifier] = deepcopy(definition)
        return deepcopy(definition)


def register_model(role, public, base_url):
    """Capture startup defaults; no runtime environment mutation is used."""
    key_env = next(
        (
            name
            for name in (
                f"{role}_API_KEY",
                "LLM_API_KEY",
                "ANTHROPIC_API_KEY"
                if public["provider"] == "anthropic"
                else "OPENAI_API_KEY",
            )
            if os.getenv(name)
        ),
        "LLM_API_KEY",
    )
    definition = {
        "kind": "model",
        **{key: public[key] for key in ("model", "provider", "max_tokens")},
        "base_url": base_url,
        "key_env": key_env,
        "temperature": 0.0,
    }
    identifier = revision(definition)
    _definitions[identifier] = definition
    _defaults[role] = identifier


def catalog():
    from deep_research.skills_loader import SKILLS_METADATA

    entries = []
    for identifier in dict.fromkeys(_defaults.values()):
        definition = archive(identifier, _definitions[identifier])
        entries.append(
            {
                "id": identifier,
                **{key: definition[key] for key in ("model", "provider", "max_tokens")},
            }
        )
    return {
        "models": entries,
        "defaults": dict(_defaults),
        "skills": deepcopy(SKILLS_METADATA),
    }


def normalize_selection(value):
    value = Selection.model_validate(value).model_dump()
    if set(value["models"]) != set(ROLES):
        raise ConfigurationError("configuration_roles_invalid")
    allowed = value["skills"]["allowed"]
    if len(set(allowed)) != len(allowed) or (
        value["skills"]["mode"] == "auto" and allowed
    ):
        raise ConfigurationError("skills_selection_invalid")
    value["skills"]["allowed"] = sorted(allowed)
    return value


def resolve_selection(value=None):
    from deep_research.model_config import public_model_config
    from deep_research.skills_loader import SKILLS_METADATA, SKILLS_BODY

    directory = catalog()
    selection = normalize_selection(
        value
        or {
            "version": 1,
            "models": directory["defaults"],
            "skills": {"mode": "auto", "allowed": []},
        }
    )
    if any(
        identifier not in _defaults.values()
        for identifier in selection["models"].values()
    ):
        raise ConfigurationError("model_configuration_unknown")
    names = (
        sorted(SKILLS_BODY)
        if selection["skills"]["mode"] == "auto"
        else selection["skills"]["allowed"]
    )
    if any(name not in SKILLS_BODY for name in names):
        raise ConfigurationError("skill_configuration_unknown")
    skills = {}
    for name in names:
        definition = {
            "kind": "skill",
            "metadata": next(item for item in SKILLS_METADATA if item["name"] == name),
            "body": SKILLS_BODY[name],
        }
        identifier = revision(definition)
        archive(identifier, definition)
        skills[name] = identifier
    snapshot = public_model_config(include_catalog=False)
    snapshot.update(
        configuration_version=1, selection=selection, skill_revisions=skills
    )
    snapshot["models"] = [
        {
            "role": role,
            "config_id": identifier,
            **{
                key: archive(identifier)[key]
                for key in ("model", "provider", "max_tokens")
            },
        }
        for role, identifier in selection["models"].items()
    ]
    return snapshot


def validate_snapshot(snapshot):
    if snapshot.get("configuration_version") != 1:
        raise ConfigurationError("configuration_version_unsupported")
    selection = normalize_selection(snapshot["selection"])
    expected = [
        {
            "role": role,
            "config_id": identifier,
            **{
                key: archive(identifier)[key]
                for key in ("model", "provider", "max_tokens")
            },
        }
        for role, identifier in selection["models"].items()
    ]
    if sorted(expected, key=lambda item: item["role"]) != sorted(
        snapshot["models"], key=lambda item: item["role"]
    ):
        raise ConfigurationError("configuration_snapshot_mismatch")
    skills = snapshot["skill_revisions"]
    if (
        selection["skills"]["mode"] == "manual"
        and sorted(skills) != selection["skills"]["allowed"]
    ):
        raise ConfigurationError("skills_snapshot_mismatch")
    for name, identifier in skills.items():
        if archive(identifier).get("metadata", {}).get("name") != name:
            raise ConfigurationError("skills_snapshot_mismatch")


@contextmanager
def configuration_scope(snapshot):
    if snapshot and snapshot.get("configuration_version") == 1:
        validate_snapshot(snapshot)
    else:
        snapshot = None
    token = _active.set(snapshot)
    try:
        yield
    finally:
        _active.reset(token)


def configured_node(function):
    if inspect.iscoroutinefunction(function):

        @wraps(function)
        async def async_node(state):
            with configuration_scope(state.get("effective_config")):
                return await function(state)

        return async_node

    @wraps(function)
    def sync_node(state):
        with configuration_scope(state.get("effective_config")):
            return function(state)

    return sync_node


def selected_model(role, fallback, *, tools=None, retry=False):
    snapshot = _active.get()
    if snapshot is None:
        return fallback
    identifier = snapshot["selection"]["models"][role]
    if identifier == _defaults.get(role):
        return fallback
    definition = archive(identifier)
    key = (role, identifier, retry)
    with _lock:
        if key not in _models:
            from deep_research.model_config import (
                init_chat_model,
                get_agent_rate_limiter,
            )

            kwargs = {
                "model": definition["model"],
                "model_provider": definition["provider"],
                "temperature": definition["temperature"],
            }
            if definition["base_url"]:
                kwargs["base_url"] = definition["base_url"]
            if credential := os.getenv(definition["key_env"]):
                kwargs["api_key"] = credential
            if definition["max_tokens"] is not None:
                kwargs["max_tokens"] = definition["max_tokens"]
            if role in ("RESEARCHER", "SUMMARIZATION", "COMPRESSION"):
                kwargs["rate_limiter"] = get_agent_rate_limiter()
            model = init_chat_model(**kwargs)
            if tools is not None:
                model = model.bind_tools(tools)
            if retry:
                model = model.with_retry(
                    stop_after_attempt=3, wait_exponential_jitter=True
                )
            _models[key] = model
        return _models[key]


def active_skills():
    snapshot = _active.get()
    if snapshot is None:
        return None
    return {
        name: archive(identifier)
        for name, identifier in snapshot["skill_revisions"].items()
    }
