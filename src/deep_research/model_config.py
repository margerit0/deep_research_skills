"""由环境变量驱动的集中式聊天模型工厂 (chat-model factory)。

本项目中所有聊天模型的实例化都经由 ``get_chat_model`` 完成，
它会从环境变量中读取按角色 (role) 区分的配置。这样模型选择就不会
硬编码在源码里：只需修改 ``.env``，同一套图 (graphs) 即可对接
OpenAI、Anthropic 或任意 OpenAI 兼容网关 (如 ModelScope 上的 Qwen、OpenRouter)。

环境变量 (Env vars)
-------------------
共享 / 全局默认值 (提供商级别):
    LLM_PROVIDER   - 可选，默认 ``"openai"``；会作为 ``model_provider``
                     转发给 ``init_chat_model``。
    LLM_BASE_URL   - 可选；OpenAI 兼容端点的 base URL。
    LLM_API_KEY    - 可选；API key。未设置时，由底层提供商自身的
                     环境变量查找逻辑接管 (如 ``OPENAI_API_KEY``)。
    AGENT_RPM      - 可选；若设置 (>0)，则所有传入
                     ``rate_limiter=get_agent_rate_limiter()`` 的调用方 (RESEARCHER /
                     SUMMARIZATION / COMPRESSION) 共享同一个请求速率限流器，
                     上限为该值 (请求数/分钟)，且不允许突发。用于遵守
                     网关的 RPM 上限并避免被 WAF 封禁 IP。

按角色 (必需):
    {ROLE}_MODEL        - 传给 ``init_chat_model`` 的模型名。

按角色 (可选；未设置时回退到对应的 ``LLM_*`` 全局变量):
    {ROLE}_PROVIDER     - 仅对该角色覆盖 ``LLM_PROVIDER``。
    {ROLE}_BASE_URL     - 仅对该角色覆盖 ``LLM_BASE_URL``。
    {ROLE}_API_KEY      - 仅对该角色覆盖 ``LLM_API_KEY``。
    {ROLE}_MAX_TOKENS   - 覆盖 ``max_tokens`` 参数。

本项目使用的角色:
    SCOPING, RESEARCHER, SUPERVISOR, SUMMARIZATION, COMPRESSION, FINAL_REPORT。
    如需自定义角色 (如 JUDGE)，至少设置 ``{ROLE}_MODEL`` 即可。

``.env`` 配置示例 —— agent 走 Qwen 网关，judge 直连 OpenAI::

    LLM_PROVIDER=openai
    LLM_BASE_URL=https://api-inference.modelscope.cn/v1
    LLM_API_KEY=ms-xxxxxxxxxxxx
    SCOPING_MODEL=Qwen/Qwen3.5-397B-A17B

    JUDGE_MODEL=gpt-4o
    JUDGE_BASE_URL=https://api.openai.com/v1
    JUDGE_API_KEY=sk-xxxxxxxxxxxx
"""

import os
import threading
from typing import Optional

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.rate_limiters import InMemoryRateLimiter


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Required env var {name!r} is not set. Check your .env file."
        )
    return value


def _role_or_global(role_upper: str, suffix: str) -> Optional[str]:
    """优先读取 ``{ROLE}_{SUFFIX}``，未设置时回退到 ``LLM_{SUFFIX}``。"""
    value = os.getenv(f"{role_upper}_{suffix}")
    if value:
        return value
    return os.getenv(f"LLM_{suffix}")


_agent_rate_limiter: Optional[InMemoryRateLimiter] = None
_agent_rate_limiter_lock = threading.Lock()


def get_agent_rate_limiter() -> Optional[InMemoryRateLimiter]:
    """返回进程级共享的限流器 (rate limiter)，用于 agent 侧的模型调用。

    速率上限为 ``AGENT_RPM`` (环境变量) 请求数/分钟。当 AGENT_RPM 未设置或
    为非正数时返回 ``None`` (调用不做任何限流)。采用单例共享，使 RESEARCHER +
    SUMMARIZATION + COMPRESSION (同一端点) 共用一份 RPM 预算，而不是各占一份
    变成 3 倍。``max_bucket_size=1`` ⇒ 严格的请求间隔、不允许突发 ——
    正是一波同时并发的请求触发了该网关的 WAF，导致我们的 IP 被封禁。
    Judge 跑在另一个端点上、有自己的并发上限，因此这里有意不对其限流。
    """
    global _agent_rate_limiter
    if _agent_rate_limiter is None:
        rpm_raw = os.getenv("AGENT_RPM")
        try:
            rpm = float(rpm_raw) if rpm_raw else 0.0
        except ValueError:
            rpm = 0.0
        if rpm > 0:
            with _agent_rate_limiter_lock:
                if _agent_rate_limiter is None:
                    _agent_rate_limiter = InMemoryRateLimiter(
                        requests_per_second=rpm / 60.0,
                        check_every_n_seconds=0.1,
                        max_bucket_size=1,
                    )
    return _agent_rate_limiter


def get_chat_model(
    role: str,
    *,
    max_tokens: Optional[int] = None,
    temperature: float = 0.0,
    rate_limiter=None,
) -> BaseChatModel:
    """根据环境变量驱动的配置，为指定角色构建聊天模型。

    Args:
        role: 逻辑角色名 (如 ``"SCOPING"``)。会与 ``_MODEL`` 等后缀
            组合后用于查找环境变量。
        max_tokens: 默认的补全 token 上限。若设置了
            ``{ROLE}_MAX_TOKENS`` 则被其覆盖。
        temperature: 采样温度。

    Returns:
        配置完成的 ``BaseChatModel`` 实例。
    """
    role_upper = role.upper()
    model_name = _required_env(f"{role_upper}_MODEL")

    env_max_tokens = os.getenv(f"{role_upper}_MAX_TOKENS")
    effective_max_tokens = int(env_max_tokens) if env_max_tokens else max_tokens

    kwargs: dict = {
        "model": model_name,
        "model_provider": _role_or_global(role_upper, "PROVIDER") or "openai",
        "temperature": temperature,
    }
    base_url = _role_or_global(role_upper, "BASE_URL")
    if base_url:
        kwargs["base_url"] = base_url
    api_key = _role_or_global(role_upper, "API_KEY")
    if api_key:
        kwargs["api_key"] = api_key
    if effective_max_tokens is not None:
        kwargs["max_tokens"] = effective_max_tokens
    if rate_limiter is not None:
        kwargs["rate_limiter"] = rate_limiter

    return init_chat_model(**kwargs)
