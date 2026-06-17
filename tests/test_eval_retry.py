"""scripts/_eval_retry.py 的单元测试。"""

import os
import unittest
from unittest.mock import MagicMock, patch

import httpx
import openai
import requests

# 不必预设 *_MODEL —— _eval_retry 不触发任何 LLM 实例化.
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from scripts import _eval_retry


def _make_rate_limit_error(message: str = "boom") -> openai.RateLimitError:
    response = httpx.Response(429, request=httpx.Request("POST", "http://x"))
    return openai.RateLimitError(message, response=response, body=None)


def _make_connection_error() -> openai.APIConnectionError:
    return openai.APIConnectionError(request=httpx.Request("POST", "http://x"))


def _make_internal_server_error() -> openai.InternalServerError:
    response = httpx.Response(500, request=httpx.Request("POST", "http://x"))
    return openai.InternalServerError("upstream 500", response=response, body=None)


class WithRetryTests(unittest.TestCase):
    def test_returns_immediately_on_success(self):
        fn = MagicMock(return_value="ok")
        wrapped = _eval_retry.with_retry(fn)

        with patch.object(_eval_retry.time, "sleep") as sleep_mock:
            result = wrapped("a", b=1)

        self.assertEqual(result, "ok")
        fn.assert_called_once_with("a", b=1)
        sleep_mock.assert_not_called()

    def test_retries_then_succeeds_with_correct_backoff(self):
        fn = MagicMock(
            side_effect=[
                _make_rate_limit_error("first"),
                _make_connection_error(),
                "ok",
            ]
        )
        wrapped = _eval_retry.with_retry(fn)

        with patch.object(_eval_retry.time, "sleep") as sleep_mock:
            result = wrapped()

        self.assertEqual(result, "ok")
        self.assertEqual(fn.call_count, 3)
        self.assertEqual(
            [call.args[0] for call in sleep_mock.call_args_list],
            list(_eval_retry.RETRY_DELAYS[:2]),
        )

    def test_exhausts_retries_then_raises_last_exception(self):
        # 前 len(RETRY_DELAYS) 次失败耗尽全部重试, 最后一次尝试的异常应原样抛出,
        # 退避序列恰为完整的 RETRY_DELAYS (断言派生自常量, 调延迟时不再失同步).
        last_exc = _make_internal_server_error()
        fn = MagicMock(
            side_effect=[
                _make_rate_limit_error(str(i))
                for i in range(len(_eval_retry.RETRY_DELAYS))
            ]
            + [last_exc]
        )
        wrapped = _eval_retry.with_retry(fn)

        with patch.object(_eval_retry.time, "sleep") as sleep_mock:
            with self.assertRaises(openai.InternalServerError) as cm:
                wrapped()

        self.assertIs(cm.exception, last_exc)
        self.assertEqual(fn.call_count, len(_eval_retry.RETRY_DELAYS) + 1)
        self.assertEqual(
            [call.args[0] for call in sleep_mock.call_args_list],
            list(_eval_retry.RETRY_DELAYS),
        )

    def test_does_not_retry_non_listed_exception(self):
        fn = MagicMock(side_effect=KeyError("research_brief"))
        wrapped = _eval_retry.with_retry(fn)

        with patch.object(_eval_retry.time, "sleep") as sleep_mock:
            with self.assertRaises(KeyError):
                wrapped()

        fn.assert_called_once()
        sleep_mock.assert_not_called()

    def test_apitimeout_is_retried_as_connection_subclass(self):
        timeout_exc = openai.APITimeoutError(
            request=httpx.Request("POST", "http://x")
        )
        fn = MagicMock(side_effect=[timeout_exc, "ok"])
        wrapped = _eval_retry.with_retry(fn)

        with patch.object(_eval_retry.time, "sleep") as sleep_mock:
            result = wrapped()

        self.assertEqual(result, "ok")
        self.assertEqual(fn.call_count, 2)
        sleep_mock.assert_called_once_with(_eval_retry.RETRY_DELAYS[0])

    def test_requests_http_error_is_retried(self):
        # 第三方 Tavily 网关持续故障窗下, utils 调用点的 6 次重试耗尽后向上抛
        # requests.exceptions.HTTPError (tavily-python 对 5xx 走 raise_for_status)。
        # eval 层必须把它当瞬时故障整案重试, 否则该案直接判死
        # (2026-06-13 实测: 一段故障窗杀掉 10 案中的 7 案)。
        response = requests.models.Response()
        response.status_code = 554
        http_error = requests.exceptions.HTTPError(
            "554 Server Error", response=response
        )
        fn = MagicMock(side_effect=[http_error, "ok"])
        wrapped = _eval_retry.with_retry(fn)

        with patch.object(_eval_retry.time, "sleep") as sleep_mock:
            result = wrapped()

        self.assertEqual(result, "ok")
        self.assertEqual(fn.call_count, 2)
        sleep_mock.assert_called_once_with(_eval_retry.RETRY_DELAYS[0])


if __name__ == "__main__":
    unittest.main()
