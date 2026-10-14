"""Public, credential-free state shared by the full graph and Atlas."""

import os
import re
from typing import Literal, NotRequired, TypedDict
from urllib.parse import urlsplit


ResearchStatus = Literal["running", "awaiting_input", "succeeded", "failed", "partial"]
ResearchPhase = Literal["clarify", "brief", "research", "writing", "complete"]


class ResearchSource(TypedDict):
    """Actually retrieved evidence; explicit-page HTTP reads carry provenance."""

    title: str
    url: str
    retrieval: NotRequired[Literal["specified_url"]]


class ResearchError(TypedDict):
    """A safe error summary; provider payloads stay in backend diagnostics."""

    code: str
    message: str
    node: str


def message_text(content) -> str:
    """Read text from both plain and provider-specific content blocks."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "\n".join(
            block["text"]
            for block in content
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        ).strip()
    return ""


def is_research_note(content) -> bool:
    """Exclude empty outputs and the shared researcher failure marker."""
    text = message_text(content)
    return bool(text) and not text.startswith("## 研究未完成")


def merge_sources(*groups: list[ResearchSource]) -> list[ResearchSource]:
    """Deduplicate safe HTTP sources, retaining their search titles."""
    result: dict[str, ResearchSource] = {}
    for group in groups:
        for source in group:
            url = source.get("url", "").strip()
            try:
                parsed = urlsplit(url)
                valid = parsed.scheme in {"http", "https"} and parsed.hostname
                valid = valid and not parsed.username and not parsed.password
            except ValueError:
                valid = False
            if valid:
                result.setdefault(
                    url, {"url": url, "title": source.get("title") or url,
                          **({"retrieval": "specified_url"} if source.get("retrieval") == "specified_url" else {})}
                )
    return list(result.values())


def extract_search_sources(content: str) -> list[ResearchSource]:
    """Parse the SOURCE/URL records emitted by utils.format_search_output."""
    matches = re.findall(
        r"^--- SOURCE \d+: (.*?) ---\r?\nURL: (https?://[^\s]+)(?:\r?\nRETRIEVAL: (specified_url))?",
        content,
        flags=re.MULTILINE,
    )
    return merge_sources([{"title": title, "url": url,
                           **({"retrieval": retrieval} if retrieval else {})}
                          for title, url, retrieval in matches])


def research_error(code: str, message: str, node: str) -> ResearchError:
    """Build the public error shape without serializing exceptions."""
    return {"code": code, "message": message, "node": node}


def log_node_failure(logger, node: str, exc: Exception) -> None:
    """Keep transport and shared Qwen diagnostics without dumping provider bodies."""
    cause = exc.__cause__
    details = {
        "exception": type(exc).__name__,
        "http_status": getattr(exc, "status_code", None),
        "cause": type(cause).__name__ if cause else None,
        "tls_verification_failed": "CERTIFICATE_VERIFY_FAILED" in str(cause),
    }
    diagnostic = str(exc)
    if diagnostic.startswith("Raw HTTP fallback received invalid choices payload"):
        diagnostic = diagnostic.split(", base_url=", 1)[0]
        for name, value in os.environ.items():
            if value and name.endswith(("_API_KEY", "_TOKEN")):
                diagnostic = diagnostic.replace(value, "[redacted]")
        details["payload_diagnostic"] = diagnostic
    logger.warning("%s failed: %s", node, details)
