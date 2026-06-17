"""Regression tests for utility helpers.

The key regression here is :func:`get_today_str`, which previously used the
glibc-only ``%-d`` strftime directive. That worked on Linux/macOS but raised
``ValueError: Invalid format string`` on Windows, taking down the
``compress_research`` node of the research agent (and silently degrading the
webpage summarizer fallback).

Also covers :func:`process_search_results`, which is parallelized to avoid
sequential summarize-LLM latency stacking up inside a single tavily_search call.
"""

import os
import re
import time
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

import requests
from tavily.errors import ForbiddenError
from tavily.errors import TimeoutError as TavilyTimeoutError

# utils.py has heavy import-time side effects (chat-model construction +
# TavilyClient init) that pull in env vars unrelated to get_today_str itself.
# Inject dummies so this test stays a pure unit test and doesn't depend on a
# populated .env file.
os.environ.setdefault("SUMMARIZATION_MODEL", "dummy/model")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("TAVILY_API_KEY", "test-key")

from deep_research import utils  # noqa: E402
from deep_research.utils import (  # noqa: E402
    get_today_str,
    process_search_results,
)


_WEEKDAYS = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}
_MONTHS = {
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
}

# Matches strings like "Sun May 24, 2026" (day has no leading zero).
_DATE_PATTERN = re.compile(
    r"(?P<weekday>[A-Z][a-z]{2}) "
    r"(?P<month>[A-Z][a-z]{2}) "
    r"(?P<day>\d{1,2}), "
    r"(?P<year>\d{4})"
)


class GetTodayStrTests(unittest.TestCase):
    def test_returns_human_readable_date_on_current_platform(self):
        # On Windows this previously raised ValueError because of the
        # glibc-only %-d directive in the strftime call.
        result = get_today_str()

        match = _DATE_PATTERN.fullmatch(result)
        self.assertIsNotNone(
            match, f"Unexpected format from get_today_str(): {result!r}"
        )
        assert match is not None  # narrow type for mypy/pyright

        self.assertIn(match.group("weekday"), _WEEKDAYS)
        self.assertIn(match.group("month"), _MONTHS)

        now = datetime.now()
        self.assertEqual(int(match.group("day")), now.day)
        self.assertEqual(int(match.group("year")), now.year)


class ProcessSearchResultsParallelTests(unittest.TestCase):
    """`process_search_results` must run per-URL summarize in parallel.

    Sequential execution made a single `tavily_search(...)` accumulate ~3x the
    LLM-summarize latency. We mock `summarize_webpage_content` with a fixed
    sleep and assert the wall time is closer to one-call's latency than to
    n-calls'.
    """

    SLEEP_PER_CALL = 0.3
    N_RESULTS = 3

    def _fake_results(self) -> dict:
        return {
            f"https://example.com/{i}": {
                "title": f"t{i}",
                "content": f"c{i}",
                "raw_content": f"r{i}",
            }
            for i in range(self.N_RESULTS)
        }

    def test_parallel_wall_time(self):
        def fake_summarize(raw: str) -> str:
            time.sleep(self.SLEEP_PER_CALL)
            return f"summary-of-{raw}"

        with patch.object(utils, "summarize_webpage_content", side_effect=fake_summarize):
            t0 = time.time()
            out = process_search_results(self._fake_results())
            elapsed = time.time() - t0

        self.assertEqual(len(out), self.N_RESULTS)
        for i in range(self.N_RESULTS):
            url = f"https://example.com/{i}"
            self.assertEqual(out[url]["title"], f"t{i}")
            self.assertEqual(out[url]["content"], f"summary-of-r{i}")

        # Sequential baseline would be N * SLEEP_PER_CALL = 0.9s.
        # Parallel should be ~0.3s + thread-pool overhead. We pick 0.6s as a
        # robust threshold that still proves parallelism without being flaky.
        sequential_baseline = self.N_RESULTS * self.SLEEP_PER_CALL
        self.assertLess(
            elapsed,
            sequential_baseline * 0.7,
            f"process_search_results took {elapsed:.2f}s for {self.N_RESULTS} "
            f"x {self.SLEEP_PER_CALL}s mock summaries; sequential baseline "
            f"{sequential_baseline:.2f}s — looks unparallelized.",
        )

    def test_skips_summarize_when_no_raw_content(self):
        # If raw_content is absent, the function should use existing `content`
        # and not call summarize_webpage_content at all.
        results = {
            "https://example.com/a": {
                "title": "ta",
                "content": "pre-summarized-a",
                # no raw_content
            }
        }
        calls = []

        def fake_summarize(raw: str) -> str:
            calls.append(raw)
            return "should-not-be-called"

        with patch.object(utils, "summarize_webpage_content", side_effect=fake_summarize):
            out = process_search_results(results)

        self.assertEqual(out["https://example.com/a"]["content"], "pre-summarized-a")
        self.assertEqual(calls, [])

    def test_empty_input(self):
        self.assertEqual(process_search_results({}), {})


def _http_error(status_code: int) -> requests.exceptions.HTTPError:
    """构造带响应状态码的 HTTPError, 模拟第三方网关 raise_for_status 的抛错。"""
    response = requests.models.Response()
    response.status_code = status_code
    return requests.exceptions.HTTPError(
        f"{status_code} Server Error", response=response
    )


class TavilySearchRetryTests(unittest.TestCase):
    """tavily_client.search 的瞬时故障重试。

    第三方 Tavily 网关 (TAVILY_API_URL) 偶发瞬时 5xx (proxy_error: upstream
    unavailable), tavily-python 对 5xx 走 raise_for_status 抛
    requests.exceptions.HTTPError —— 不重试会直接杀死整个 agent run。
    约定: 按 6 个互不相同且递增的间隔重试, 6 次重试耗尽后把原异常抛出;
    配额/鉴权类 4xx (tavily 自定义异常) 不可重试, 必须立即抛出。
    """

    def _search(self, query: str = "q") -> list:
        return utils.tavily_search_multiple([query], max_results=1)

    def test_retry_delays_are_six_distinct_increasing(self):
        delays = utils.TAVILY_RETRY_DELAYS
        self.assertEqual(len(delays), 6, "需求: 重试 6 次")
        self.assertEqual(len(set(delays)), 6, "需求: 间隔互不相同")
        self.assertEqual(list(delays), sorted(delays), "间隔应递增")

    def test_transient_5xx_retried_then_succeeds(self):
        ok = {"results": [{"url": "https://e.com", "title": "t", "content": "c"}]}
        search_mock = MagicMock(side_effect=[_http_error(500), _http_error(554), ok])

        with patch.object(utils.tavily_client, "search", search_mock), \
                patch.object(utils, "time") as time_mock:
            result = self._search()

        self.assertEqual(result, [ok])
        self.assertEqual(search_mock.call_count, 3)
        self.assertEqual(
            [c.args[0] for c in time_mock.sleep.call_args_list],
            list(utils.TAVILY_RETRY_DELAYS[:2]),
        )

    def test_raises_original_error_after_six_retries(self):
        search_mock = MagicMock(side_effect=_http_error(502))

        with patch.object(utils.tavily_client, "search", search_mock), \
                patch.object(utils, "time") as time_mock:
            with self.assertRaises(requests.exceptions.HTTPError):
                self._search()

        self.assertEqual(search_mock.call_count, 7, "1 次原始调用 + 6 次重试")
        self.assertEqual(
            [c.args[0] for c in time_mock.sleep.call_args_list],
            list(utils.TAVILY_RETRY_DELAYS),
        )

    def test_tavily_timeout_is_retried(self):
        ok = {"results": []}
        search_mock = MagicMock(side_effect=[TavilyTimeoutError(60), ok])

        with patch.object(utils.tavily_client, "search", search_mock), \
                patch.object(utils, "time"):
            result = self._search()

        self.assertEqual(result, [ok])
        self.assertEqual(search_mock.call_count, 2)

    def test_quota_error_not_retried(self):
        # ForbiddenError = 月度配额耗尽/计划限制, 重试只会白等几分钟。
        search_mock = MagicMock(
            side_effect=ForbiddenError("exceeds your plan's set usage limit")
        )

        with patch.object(utils.tavily_client, "search", search_mock), \
                patch.object(utils, "time") as time_mock:
            with self.assertRaises(ForbiddenError):
                self._search()

        self.assertEqual(search_mock.call_count, 1)
        time_mock.sleep.assert_not_called()

    def test_http_4xx_not_retried(self):
        # tavily 对常见 4xx 抛自定义异常, 但网关若直接回 4xx HTTPError
        # 也属于请求本身的问题, 不应重试。
        search_mock = MagicMock(side_effect=_http_error(404))

        with patch.object(utils.tavily_client, "search", search_mock), \
                patch.object(utils, "time") as time_mock:
            with self.assertRaises(requests.exceptions.HTTPError):
                self._search()

        self.assertEqual(search_mock.call_count, 1)
        time_mock.sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
