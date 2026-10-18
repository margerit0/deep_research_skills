"""Carry user requirements independently of model-written delegations.

Explicit named Skills and URL-only source lists have runtime enforcement. Other
requirements remain verbatim context, not an LLM paraphrase of a paraphrase.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from html.parser import HTMLParser
import re
from typing import TypedDict
from urllib.parse import urljoin, urlsplit, urlunsplit
import os

import requests


class ResearchConstraints(TypedDict):
    required_skills: list[str]
    allowed_source_urls: list[str] | None


URL_PATTERN = re.compile(r"https?://[^\s<>\"'`，。；、（）\[\]]+", re.I)
_SCOPE_MARKER = re.compile(
    r"(?:资料|来源|证据)(?:范围)?\s*(?:严格)?\s*(?:固定为|限定为|限定在|限于|仅限)|"
    r"(?:仅|只|只能)(?:使用|依据|依照|基于|参考|检索|采用)|"
    r"\b(?:sources?|evidence)\s*(?:are\s*)?(?:restricted|limited)\s+to\b|"
    r"\b(?:use|consult|cite|search)\s+only\b|\bonly\s+(?:use|consult|cite)\b",
    re.I,
)
_SKILL_NAME = re.compile(
    r"\bskill_name\s*[`\"']?\s*(?:=|:|：|为|使用|设为|是)\s*[`\"']?([a-zA-Z0-9][\w-]*)|"
    r"(?:加载\s*|\bload\s+)(?:skill\s+)?[`\"']?([a-zA-Z0-9]+(?:-[a-zA-Z0-9]+)+)",
    re.I,
)


def normalized_url(url: str) -> str | None:
    """Ignore fragments/default ports only; preserve path, version and query."""
    try:
        parts = urlsplit(url)
        if (parts.scheme.lower() not in {"http", "https"} or not parts.hostname
                or parts.username or parts.password or re.search(r"[\s\\\x00-\x1f]", url)):
            return None
        host = parts.hostname.lower()
        if ":" in host:
            host = f"[{host}]"
        port = parts.port
        if port and (parts.scheme.lower(), port) not in {("https", 443), ("http", 80)}:
            host += f":{port}"
        return urlunsplit((parts.scheme.lower(), host, parts.path or "/", parts.query, ""))
    except ValueError:
        return None


def extract_urls(text: str) -> list[str]:
    """Keep balanced URL parentheses while removing Markdown's closing paren."""
    urls = []
    for token in URL_PATTERN.findall(text):
        token = token.rstrip(".,;")
        while token.endswith(")") and token.count(")") > token.count("("):
            token = token[:-1]
        urls.append(token)
    return urls


def resolve_constraints(user_messages: list[str]) -> ResearchConstraints:
    """Recognize explicit tool names and URL lists without inventing restrictions.

    A later explicit source list replaces an earlier one during clarification.
    Merely mentioning a URL, an official-source preference or a site: query does
    not create a URL allowlist. The original text always accompanies this result.
    """
    skills: list[str] = []
    allowed = None
    for text in user_messages:
        for match in _SKILL_NAME.finditer(text):
            name = next(value for value in match.groups() if value)
            prefix = text[max(0, match.start() - 20):match.start()]
            if re.search(r"(?:不要|无需|不再|do not|don't)\s*$", prefix, re.I):
                skills = [item for item in skills if item != name]
            elif name not in skills:
                skills.append(name)
        for marker in _SCOPE_MARKER.finditer(text):
            # Lists may span lines, but stop at the next sentence/paragraph.
            block = re.split(r"[。；;]|\n\s*\n|\.(?=\s|$)", text[marker.start():], maxsplit=1)[0]
            urls = extract_urls(block)
            if urls:
                allowed = list(dict.fromkeys(
                    normalized for url in urls
                    if (normalized := normalized_url(url))
                ))
    return {"required_skills": skills, "allowed_source_urls": allowed}


def constraints_for(state) -> ResearchConstraints:
    existing = state.get("research_constraints")
    if existing is not None:
        return existing
    text = state.get("user_requirements") or state.get("research_brief") or state.get("research_topic", "")
    messages = [text] if text else [
        message.content for message in state.get("researcher_messages", [])
        if getattr(message, "type", None) == "human" and isinstance(message.content, str)
        and getattr(message, "name", None) != "loaded_methodology"
    ]
    return resolve_constraints(messages)


def requirements_context(state) -> str:
    """Global context is shared; other workers' conversations remain private."""
    brief = state.get("research_brief", "")
    original = state.get("user_requirements", "")
    return (
        "\n<Global requirements>\n用户原始要求优先于简报转述、子任务和 Skill 默认方法。"
        "只完成分配给你的子任务；全局上下文用于遵守流程、来源和输出限制，"
        "不要求重复研究其他子任务。\n"
        f"<Original user requirements>\n{original}\n</Original user requirements>\n"
        f"<Research brief>\n{brief}\n</Research brief>\n</Global requirements>\n"
    ) if brief or original else ""


def approximate_report_length(state) -> int | None:
    """Recognize only an explicit approximate Chinese length in user text."""
    text = state.get("user_requirements", "")
    matches = list(re.finditer(r"(?:大约|约为|约)\s*(\d{2,5})\s*(?:个)?(?:汉字|字)(?!节)", text))
    return int(matches[-1][1]) if matches else None


def report_length_guidance(state) -> str:
    """Restate an explicit approximate Chinese length, never infer from notes."""
    target = approximate_report_length(state)
    if target is None:
        return ""
    return (
        f"\n<Short report delivery>\n用户给出的全文篇幅目标是约 {target} 个汉字。请瞄准 {target} 个汉字，"
        f"写作预算为 {round(target * 0.9)}–{round(target * 1.1)} 个汉字；"
        "这是全文总预算，不是每节预算。计入标题和建议，不计末尾来源列表；"
        "只统计中文汉字，英文字母、数字、标点、代码名和引用编号不计入，不能靠英文标识符凑篇幅。"
        "先在预算内保留改变结论的限定。用自然的中文短句回答比较问题，不按来源目录逐项复述。"
        "用户未要求实现教程时，不列初始化 API、宏、代码或平台构建步骤；"
        "只保留回答问题必需的操作名称和实质约束，不堆叠英文标识符。"
        "次要事实写不全对象范围、条件和例外时，删去整项，不把具体类别泛化；"
        "即使写‘可能有风险’，也要交代来源限定的对象、使用规模或其他触发条件，不能只保留‘可能’二字。"
        "不要把不同规则的适用条件或解决办法合并成一句笼统结论。"
        "未知参数与行为说明须覆盖报告提到的各个选项。"
        "删除重复概览、重复结论和未要求的未来计划。不要输出字数说明。\n</Short report delivery>\n"
    )


class _SourceScope:
    def __init__(self, constraints):
        urls = constraints.get("allowed_source_urls")
        self.allowed = None if urls is None else {normalized_url(url) for url in urls}
        if self.allowed is not None:
            self.allowed.discard(None)
        self.audit: list[dict] = []
        self.verified: dict[str, tuple[str, int | None]] = {}

    def permits(self, url):
        normalized = normalized_url(url)
        return bool(normalized and (self.allowed is None or normalized in self.allowed))


_source_scope = ContextVar("research_source_scope", default=None)


@contextmanager
def source_scope(constraints):
    scope = _SourceScope(constraints)
    token = _source_scope.set(scope)
    try:
        yield scope.audit
    finally:
        _source_scope.reset(token)


def has_source_restriction():
    scope = _source_scope.get()
    return scope is not None and scope.allowed is not None


def _verify_source_url(url, scope):
    """Check redirects before consuming search content for an exact-page scope."""
    if url in scope.verified:
        return scope.verified[url]
    current = url
    proxies = {scheme: value for scheme in ("http", "https")
               if (value := os.getenv(f"TAVILY_{scheme.upper()}_PROXY"))}
    status = None
    try:
        for _ in range(6):
            # Do not request a redirect target outside the user's allowlist.
            if not scope.permits(current):
                result = ("redirect_out_of_scope", status)
                break
            with requests.get(current, allow_redirects=False, stream=True,
                              timeout=(10, 25), proxies=proxies or None) as response:
                status = response.status_code
                if not scope.permits(response.url):
                    result = ("redirect_out_of_scope", status)
                    break
                if status in {301, 302, 303, 307, 308}:
                    location = response.headers.get("Location")
                    if not location:
                        result = ("redirect_unverified", status)
                        break
                    current = urljoin(current, location)
                    continue
                result = ("accepted" if status == 200 else "source_http_error", status)
                break
        else:
            result = ("redirect_limit", status)
    except requests.RequestException:
        result = ("source_unverified", status)
    scope.verified[url] = result
    return result


def filter_search_results(search_results: list[dict]) -> list[dict]:
    """Keep raw-hit decisions separate; excluded content never reaches an LLM."""
    scope = _source_scope.get()
    if scope is None or scope.allowed is None:
        return search_results
    filtered = []
    for response in search_results:
        accepted = []
        for item in response.get("results", []):
            url = item.get("url", "")
            status = None
            if not scope.permits(url):
                reason = "out_of_scope"
            elif any(item.get(key) and not scope.permits(item[key])
                     for key in ("final_url", "resolved_url")):
                reason = "redirect_out_of_scope"
            else:
                reason, status = _verify_source_url(url, scope)
            scope.audit.append({"url": url, "decision": reason, "http_status": status, "retrieval": "search"})
            if reason == "accepted":
                accepted.append(item)
        # Drop provider answers/images; only accepted result bodies are consumed.
        filtered.append({"results": accepted})
    return filtered


class _PageText(HTMLParser):
    """Extract readable HTML without executing scripts or following page links."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.title = []
        self.in_title = False
        self.blocked = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "nav", "header", "footer"}:
            self.blocked += 1
        if tag == "title":
            self.in_title = True
        if tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "pre"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "nav", "header", "footer"}:
            self.blocked = max(0, self.blocked - 1)
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)
        if not self.blocked:
            self.parts.append(data)


def retrieve_specified_sources(max_results=3, excluded_urls=()):
    """If search misses an exact user-supplied page, read that page explicitly.

    This is direct HTTP evidence, never recorded as a search-engine hit. No URL
    comes from model invention or links in a page; redirects stay in the scope.
    """
    scope = _source_scope.get()
    if scope is None or scope.allowed is None:
        return []
    results = []
    proxies = {scheme: value for scheme in ("http", "https")
               if (value := os.getenv(f"TAVILY_{scheme.upper()}_PROXY"))}
    remaining = scope.allowed - {normalized_url(url) for url in excluded_urls}
    for url in sorted(remaining)[:max(0, min(max_results, 3))]:
        current, status, reason = url, None, "source_unverified"
        try:
            for _ in range(6):
                if not scope.permits(current):
                    reason = "redirect_out_of_scope"
                    break
                with requests.get(current, allow_redirects=False, stream=True,
                                  timeout=(10, 25), proxies=proxies or None) as response:
                    status = response.status_code
                    if not scope.permits(response.url):
                        reason = "redirect_out_of_scope"
                        break
                    if status in {301, 302, 303, 307, 308}:
                        location = response.headers.get("Location")
                        if not location:
                            reason = "redirect_unverified"
                            break
                        current = urljoin(current, location)
                        continue
                    if status != 200:
                        reason = "source_http_error"
                        break
                    mime = response.headers.get("Content-Type", "").lower()
                    if not any(kind in mime for kind in ("text/", "application/xhtml")):
                        break
                    chunks, size = [], 0
                    for chunk in response.iter_content(chunk_size=16384):
                        size += len(chunk)
                        if size > 1_000_000:
                            break
                        chunks.append(chunk)
                    if size > 1_000_000:
                        break
                    body = b"".join(chunks).decode("utf-8", errors="replace")
                    title = url
                    if "html" in mime:
                        page = _PageText()
                        page.feed(body)
                        body = "\n".join(line.strip() for line in "".join(page.parts).splitlines() if line.strip())
                        title = "".join(page.title).strip() or url
                    if not body.strip():
                        break
                    results.append({"url": url, "title": title, "raw_content": body,
                                    "retrieval": "specified_url"})
                    reason = "accepted"
                    break
            else:
                reason = "redirect_limit"
        except requests.RequestException:
            pass
        scope.audit.append({"url": url, "decision": reason, "http_status": status,
                            "retrieval": "specified_url"})
    return [{"results": results}]


def allowed_sources(sources, constraints):
    scope = _SourceScope(constraints)
    return [source for source in sources if scope.permits(source.get("url", ""))]


def report_citations_within_sources(report, sources) -> bool:
    """Validate URLs against actually consumed sources, never a model's URL list."""
    accepted = {normalized_url(source["url"]) for source in sources}
    return all(normalized_url(url) in accepted for url in extract_urls(report))
