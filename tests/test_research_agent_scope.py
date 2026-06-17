"""Regression tests for research scoping message handling."""

import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from deep_research import research_agent_scope


class _FakeStructuredOutputModel:
    def __init__(self, response, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def invoke(self, payload):
        self.calls.append(payload)
        if self.error is not None:
            raise self.error
        return self.response


class _FakeModel:
    def __init__(
        self,
        response,
        fallback_response=None,
        structured_error=None,
        invoke_error=None,
        bound_response=None,
        bound_error=None,
    ):
        self.response = response
        self.fallback_response = fallback_response
        self.structured_error = structured_error
        self.invoke_error = invoke_error
        self.bound_response = bound_response
        self.bound_error = bound_error
        self.structured_model = None
        self.invoke_payload = None
        self.bound_kwargs = None
        self.bound_model = None

    def with_structured_output(self, _schema):
        self.structured_model = _FakeStructuredOutputModel(
            self.response,
            error=self.structured_error,
        )
        return self.structured_model

    def bind(self, **kwargs):
        self.bound_kwargs = kwargs
        self.bound_model = _FakeStructuredOutputModel(
            self.bound_response,
            error=self.bound_error,
        )
        return self.bound_model

    def invoke(self, payload):
        self.invoke_payload = payload
        if self.invoke_error is not None:
            raise self.invoke_error
        return self.fallback_response


class ResearchAgentScopeTests(unittest.TestCase):
    def test_clarify_with_user_treats_none_messages_as_empty_history(self):
        fake_model = _FakeModel(
            research_agent_scope.ClarifyWithUser(
                need_clarification=True,
                question="Could you clarify?",
                verification="",
            )
        )

        with patch.object(research_agent_scope, "model", fake_model):
            result = research_agent_scope.clarify_with_user({"messages": None})

        self.assertEqual(result.goto, research_agent_scope.END)
        self.assertEqual(
            result.update["messages"][0].content,
            "Could you clarify?",
        )
        self.assertEqual(len(fake_model.structured_model.calls), 1)
        self.assertIsInstance(fake_model.structured_model.calls[0][0], HumanMessage)

    def test_write_research_brief_treats_none_messages_as_empty_history(self):
        fake_model = _FakeModel(
            research_agent_scope.ResearchQuestion(
                research_brief="Research the topic thoroughly",
            )
        )

        with patch.object(research_agent_scope, "model", fake_model):
            result = research_agent_scope.write_research_brief({"messages": None})

        self.assertEqual(
            result["research_brief"],
            "Research the topic thoroughly",
        )
        self.assertEqual(
            result["supervisor_messages"][0].content,
            "Research the topic thoroughly.",
        )
        self.assertEqual(len(fake_model.structured_model.calls), 1)
        self.assertIsInstance(fake_model.structured_model.calls[0][0], HumanMessage)

    def test_clarify_with_user_falls_back_to_json_text_parsing(self):
        fake_model = _FakeModel(
            response=None,
            fallback_response=AIMessage(
                content=json.dumps(
                    {
                        "need_clarification": True,
                        "question": "Which district in Hangzhou?",
                        "verification": "",
                    }
                )
            ),
            structured_error=TypeError("'NoneType' object is not iterable"),
        )

        with patch.object(research_agent_scope, "model", fake_model):
            result = research_agent_scope.clarify_with_user(
                {"messages": [HumanMessage(content="Tell me about tea shops")]}
            )

        self.assertEqual(result.goto, research_agent_scope.END)
        self.assertEqual(
            result.update["messages"][0].content,
            "Which district in Hangzhou?",
        )
        self.assertIsNotNone(fake_model.invoke_payload)

    def test_write_research_brief_falls_back_to_json_text_parsing(self):
        fake_model = _FakeModel(
            response=None,
            fallback_response=AIMessage(
                content=json.dumps(
                    {
                        "research_brief": "Research the best milk tea shops in Hangzhou."
                    }
                )
            ),
            structured_error=TypeError("'NoneType' object is not iterable"),
        )

        with patch.object(research_agent_scope, "model", fake_model):
            result = research_agent_scope.write_research_brief(
                {
                    "messages": [
                        HumanMessage(
                            content="Tell me the best milk tea shop in Hangzhou"
                        )
                    ]
                }
            )

        self.assertEqual(
            result["research_brief"],
            "Research the best milk tea shops in Hangzhou.",
        )
        self.assertIsNotNone(fake_model.invoke_payload)

    def test_write_research_brief_uses_raw_http_directly_for_qwen_json_fallback(self):
        fake_model = _FakeModel(
            response=research_agent_scope.ResearchQuestion(
                research_brief="This path should be skipped for Qwen."
            ),
        )
        fake_model.model_name = "Qwen/Qwen3.5-397B-A17B"
        raw_http_response = SimpleNamespace(
            read=lambda: json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "research_brief": "Research the best milk tea shop in Hangzhou."
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode("utf-8"),
        )

        with (
            patch.dict(
                os.environ,
                {
                    "LLM_BASE_URL": "https://api-inference.modelscope.cn/v1",
                    "LLM_API_KEY": "test-key",
                },
                clear=False,
            ),
            patch.object(research_agent_scope, "model", fake_model),
            patch("urllib.request.urlopen", return_value=raw_http_response) as mock_urlopen,
        ):
            result = research_agent_scope.write_research_brief(
                {
                    "messages": [
                        HumanMessage(
                            content="Tell me the best milk tea shop in Hangzhou"
                        )
                    ]
                }
            )

        self.assertEqual(
            result["research_brief"],
            "Research the best milk tea shop in Hangzhou.",
        )
        self.assertIsNone(fake_model.structured_model)
        self.assertIsNone(fake_model.bound_kwargs)
        self.assertEqual(mock_urlopen.call_count, 1)

    def test_write_research_brief_uses_raw_http_fallback_when_qwen_response_has_null_choices(self):
        fake_model = _FakeModel(
            response=research_agent_scope.ResearchQuestion(
                research_brief="This path should be skipped for broken Qwen responses."
            ),
            bound_error=TypeError(
                "Received response with null value for 'choices'."
            ),
        )
        fake_model.model_name = "Qwen/Qwen3.5-397B-A17B"
        raw_http_response = SimpleNamespace(
            read=lambda: json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "research_brief": "Research the best milk tea shops in Hangzhou."
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode("utf-8"),
        )

        with (
            patch.dict(
                os.environ,
                {
                    "LLM_BASE_URL": "https://api-inference.modelscope.cn/v1",
                    "LLM_API_KEY": "test-key",
                },
                clear=False,
            ),
            patch.object(research_agent_scope, "model", fake_model),
            patch("urllib.request.urlopen", return_value=raw_http_response) as mock_urlopen,
        ):
            result = research_agent_scope.write_research_brief(
                {
                    "messages": [
                        HumanMessage(
                            content="Tell me the best milk tea shop in Hangzhou"
                        )
                    ]
                }
            )

        self.assertEqual(
            result["research_brief"],
            "Research the best milk tea shops in Hangzhou.",
        )
        self.assertEqual(mock_urlopen.call_count, 1)


class StructuredOutputFallbackTests(unittest.TestCase):
    def test_invoke_with_structured_output_fallback_uses_raw_http_directly_for_qwen_json_fallback(self):
        from deep_research.structured_output_fallback import (
            invoke_with_structured_output_fallback,
        )

        class EvalResult(BaseModel):
            research_brief: str

        fake_model = _FakeModel(
            response=EvalResult(research_brief="This path should be skipped."),
        )
        raw_http_response = SimpleNamespace(
            read=lambda: json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "research_brief": "Research the best milk tea shops in Hangzhou."
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode("utf-8")
        )

        with patch(
            "deep_research.structured_output_fallback.urllib.request.urlopen",
            return_value=raw_http_response,
        ) as mock_urlopen:
            result = invoke_with_structured_output_fallback(
                fake_model,
                EvalResult,
                "Return a research brief.",
                base_url="https://api-inference.modelscope.cn/v1",
                api_key="test-key",
                model_name="Qwen/Qwen3.5-397B-A17B",
            )

        self.assertEqual(
            result.research_brief,
            "Research the best milk tea shops in Hangzhou.",
        )
        self.assertEqual(mock_urlopen.call_count, 1)
        self.assertIsNone(fake_model.bound_kwargs)

    def test_invoke_with_structured_output_fallback_uses_raw_http_when_qwen_response_has_null_choices(self):
        from deep_research.structured_output_fallback import (
            invoke_with_structured_output_fallback,
        )

        class EvalResult(BaseModel):
            research_brief: str

        fake_model = _FakeModel(
            response=EvalResult(research_brief="This path should be skipped."),
            bound_error=TypeError(
                "Received response with null value for 'choices'."
            ),
        )
        raw_http_response = SimpleNamespace(
            read=lambda: json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "research_brief": "Research the best milk tea shops in Hangzhou."
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode("utf-8"),
        )

        with patch(
            "deep_research.structured_output_fallback.urllib.request.urlopen",
            return_value=raw_http_response,
        ) as mock_urlopen:
            result = invoke_with_structured_output_fallback(
                fake_model,
                EvalResult,
                "Return a research brief.",
                base_url="https://api-inference.modelscope.cn/v1",
                api_key="test-key",
                model_name="Qwen/Qwen3.5-397B-A17B",
            )

        self.assertEqual(
            result.research_brief,
            "Research the best milk tea shops in Hangzhou.",
        )
        self.assertIsNone(fake_model.bound_kwargs)
        self.assertEqual(mock_urlopen.call_count, 1)

    def test_invoke_with_structured_output_fallback_retries_raw_http_once_for_qwen_null_choices(self):
        from deep_research.structured_output_fallback import (
            invoke_with_structured_output_fallback,
        )

        class EvalResult(BaseModel):
            research_brief: str

        fake_model = _FakeModel(
            response=EvalResult(research_brief="This path should be skipped."),
            bound_error=TypeError(
                "Received response with null value for 'choices'."
            ),
        )
        retry_responses = [
            SimpleNamespace(
                read=lambda: json.dumps(
                    {
                        "id": "chatcmpl-first",
                        "object": "",
                        "created": 0,
                        "model": "Qwen/Qwen3.5-397B-A17B",
                        "system_fingerprint": "",
                        "choices": None,
                        "usage": {
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                            "total_tokens": 0,
                        },
                    }
                ).encode("utf-8")
            ),
            SimpleNamespace(
                read=lambda: json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                            "research_brief": "Research the best milk tea shops in Hangzhou."
                                        }
                                    )
                                }
                            }
                        ]
                    }
                ).encode("utf-8")
            ),
        ]

        with patch(
            "deep_research.structured_output_fallback.urllib.request.urlopen",
            side_effect=retry_responses,
        ) as mock_urlopen:
            result = invoke_with_structured_output_fallback(
                fake_model,
                EvalResult,
                "Return a research brief.",
                base_url="https://api-inference.modelscope.cn/v1",
                api_key="test-key",
                model_name="Qwen/Qwen3.5-397B-A17B",
            )

        self.assertEqual(
            result.research_brief,
            "Research the best milk tea shops in Hangzhou.",
        )
        self.assertEqual(mock_urlopen.call_count, 2)

    def test_invoke_with_structured_output_fallback_reports_provider_diagnostics_on_terminal_invalid_payload(self):
        from deep_research.structured_output_fallback import (
            invoke_with_structured_output_fallback,
        )

        class EvalResult(BaseModel):
            research_brief: str

        fake_model = _FakeModel(
            response=EvalResult(research_brief="This path should be skipped."),
            bound_error=TypeError(
                "Received response with null value for 'choices'."
            ),
        )
        invalid_response = SimpleNamespace(
            read=lambda: json.dumps(
                {
                    "id": "chatcmpl-f0fb0721",
                    "object": "",
                    "created": 0,
                    "model": "Qwen/Qwen3.5-397B-A17B",
                    "system_fingerprint": "",
                    "choices": None,
                    "usage": {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                    },
                }
            ).encode("utf-8")
        )

        with patch(
            "deep_research.structured_output_fallback.urllib.request.urlopen",
            side_effect=[invalid_response, invalid_response],
        ):
            with self.assertRaises(ValueError) as exc_info:
                invoke_with_structured_output_fallback(
                    fake_model,
                    EvalResult,
                    "Return a research brief.",
                    base_url="https://api-inference.modelscope.cn/v1",
                    api_key="test-key",
                    model_name="Qwen/Qwen3.5-397B-A17B",
                )

        error_text = str(exc_info.exception)
        self.assertIn("choices_type=NoneType", error_text)
        self.assertIn("model=Qwen/Qwen3.5-397B-A17B", error_text)
        self.assertIn("object=''", error_text)
        self.assertIn("usage=", error_text)

    def test_invoke_with_structured_output_fallback_ignores_trailing_braced_text_after_json_object(self):
        from deep_research.structured_output_fallback import (
            invoke_with_structured_output_fallback,
        )

        class Criteria(BaseModel):
            criteria_text: str
            reasoning: str
            is_captured: bool

        fake_model = _FakeModel(
            response=None,
            fallback_response=AIMessage(
                content=(
                    '{"criteria_text":"single criterion",'
                    '"reasoning":"The brief covers the requested scope.",'
                    '"is_captured":true}\n'
                    'Audit note: keep rubric as {"criterion_id": 1}.'
                )
            ),
            structured_error=TypeError("'NoneType' object is not iterable"),
        )

        result = invoke_with_structured_output_fallback(
            fake_model,
            Criteria,
            "Evaluate whether the brief captures this criterion.",
        )

        self.assertEqual(result.criteria_text, "single criterion")
        self.assertTrue(result.is_captured)
        self.assertEqual(
            result.reasoning,
            "The brief covers the requested scope.",
        )


if __name__ == "__main__":
    unittest.main()




