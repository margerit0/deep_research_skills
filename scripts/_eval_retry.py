"""共享的上游瞬时故障重试装饰器。

被 scoping / research_agent 两个 eval 流程复用。本模块不导入任何
``deep_research.*`` 内部模块, 因此 import 它不会触发
任意模型角色的实例化 —— 让每个 eval 流程只需配置自己关心的 *_MODEL 即可。
"""

from __future__ import annotations

import functools
import sys
import time
from typing import Any, Callable, TypeVar, cast

import openai
import requests
from pydantic import ValidationError
from tavily.errors import TimeoutError as TavilyTimeoutError


# 每次重试前的 sleep 秒数 (从短到长); 长度即最大重试次数 —— 5 次重试, 总共最多 6 次尝试.
RETRY_DELAYS: tuple[int, ...] = (5, 15, 30, 60, 120)

# 只对上游瞬时类异常重试; 4xx (除 429) 属于请求本身的问题, 重试无意义.
# 同时把 LLM-as-judge 的随机性故障也纳入: judge 偶尔会返回
#   (a) 截断/缺字段的 JSON  -> pydantic.ValidationError
#   (b) 完全无法解析的文本  -> extract_json_object 抛 ValueError
# 这两种属于模型本次输出不稳定, 重试一次往往就能正常返回.
RETRY_EXCEPTIONS: tuple[type[BaseException], ...] = (
    openai.RateLimitError,        # 429
    openai.APIConnectionError,    # 含子类 APITimeoutError, 覆盖断连/超时
    openai.InternalServerError,   # 5xx
    ValidationError,              # judge 输出字段缺失/类型不符
    ValueError,                   # extract_json_object 无法定位 JSON 对象
    # tavily-python 走 requests; 本地网络抖动表现为 SSLError(UNEXPECTED_EOF)/断连/超时,
    # 同属瞬时故障 (e2e 实测: api.tavily.com SSL EOF 直接杀死整个 agent run)。
    requests.exceptions.ConnectionError,   # 含子类 SSLError
    requests.exceptions.Timeout,
    # tavily-python 对 5xx 走 raise_for_status 抛 requests.exceptions.HTTPError;
    # utils 调用点的 6 次退避重试 (~3.8min) 盖不住网关持续故障窗时, 异常会带着
    # 这个类型向上穿透杀死整案 (2026-06-13 实测: 一段故障窗杀掉 10 案中 7 案)。
    # eval 层整案重试的退避 (最长 600s) 正好覆盖这种多分钟级窗口。tavily 对 4xx
    # 抛自定义异常 (ForbiddenError 等, 不在白名单), 故这里的 HTTPError ≈ 5xx。
    requests.exceptions.HTTPError,
    # tavily-python 对请求超时不抛 requests.Timeout, 而是吞掉后重抛自定义的
    # tavily.errors.TimeoutError(Exception) —— 不在上面任何继承树上, 必须单独列入
    # (e2e 实测: skills 版 #1 因此 126s 整 agent 死亡, 重试逻辑完全没触发)。
    TavilyTimeoutError,
)


F = TypeVar("F", bound=Callable[..., Any])


def with_retry(fn: F) -> F:
    """对上游瞬时故障按 ``RETRY_DELAYS`` 退避重试.

    每次重试前向 stderr 打印一行 [retry] 日志; 重试耗尽时把最后一次异常抛出,
    交由 LangSmith ``error_handling="log"`` 接住, 不会中断整个批次评估.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        fn_label = getattr(fn, "__name__", repr(fn))
        for attempt in range(len(RETRY_DELAYS) + 1):
            try:
                return fn(*args, **kwargs)
            except RETRY_EXCEPTIONS as exc:
                if attempt >= len(RETRY_DELAYS):
                    raise
                delay = RETRY_DELAYS[attempt]
                print(
                    f"[retry] {fn_label} attempt {attempt + 1} failed "
                    f"({type(exc).__name__}: {exc}); sleeping {delay}s...",
                    file=sys.stderr,
                    flush=True,
                )
                time.sleep(delay)

    return cast(F, wrapper)
