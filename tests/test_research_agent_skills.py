"""Integration tests for research_agent_skills.

Tests don't hit real LLMs or Tavily; they verify:
- the graph compiles
- compress_research filters non-search ToolMessages out of raw_notes
- the prompt template includes all discovered skills
"""

import os
import unittest
from unittest.mock import MagicMock, patch

# Module-level side effects in utils.py and model_config require these env vars
# before any deep_research import.
os.environ.setdefault("RESEARCHER_MODEL", "dummy/model")
os.environ.setdefault("COMPRESSION_MODEL", "dummy/model")
os.environ.setdefault("SUMMARIZATION_MODEL", "dummy/model")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("TAVILY_API_KEY", "test-key")

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402


class AgentCompilationTests(unittest.TestCase):
    def test_agent_compiles(self):
        from deep_research.research_agent_skills import (
            researcher_agent_skills,
        )

        self.assertIsNotNone(researcher_agent_skills)


class CompressResearchFilterTests(unittest.TestCase):
    def test_compress_research_filters_non_search_tool_messages(self):
        from deep_research import research_agent_skills as mod

        fake_response = MagicMock()
        fake_response.content = "压缩后摘要"

        with patch.object(mod, "compress_model") as mock_model:
            mock_model.invoke.return_value = fake_response

            state = {
                "researcher_messages": [
                    HumanMessage(content="研究 X"),
                    AIMessage(content="规划阶段"),
                    ToolMessage(
                        content="SKILL_BODY_TEXT",
                        name="load_skill",
                        tool_call_id="1",
                    ),
                    ToolMessage(
                        content="TAVILY_RESULT_TEXT",
                        name="tavily_search",
                        tool_call_id="2",
                    ),
                    ToolMessage(
                        content="REFLECTION_TEXT",
                        name="think_tool",
                        tool_call_id="3",
                    ),
                ],
            }

            result = mod.compress_research(state)

        raw = "\n".join(result["raw_notes"])
        self.assertIn("TAVILY_RESULT_TEXT", raw)
        self.assertNotIn("SKILL_BODY_TEXT", raw)
        self.assertNotIn("REFLECTION_TEXT", raw)
        self.assertIn("规划阶段", raw)  # AIMessage 应保留
        self.assertEqual(result["compressed_research"], "压缩后摘要")


class PromptIntegrationTests(unittest.TestCase):
    def test_prompt_includes_all_skills(self):
        from deep_research.prompts import (
            research_agent_prompt_with_skills,
        )
        from deep_research.skills_loader import (
            SKILLS_METADATA,
            format_skills_index,
        )
        from deep_research.utils import get_today_str

        prompt = research_agent_prompt_with_skills.format(
            date=get_today_str(),
            skills_index=format_skills_index(),
        )

        self.assertGreater(len(SKILLS_METADATA), 0, "应至少加载到一个 skill")
        for skill in SKILLS_METADATA:
            self.assertIn(skill["name"], prompt)
            self.assertIn(skill["description"], prompt)


class TemplateFollowStrengthTests(unittest.TestCase):
    """Todo 2: lift skill-template following from 部分 (1/3) toward 完全 (≥3/3).

    Single-agent mode was already 3/3 after the B 补救 commit; supervisor-dispatch
    mode was still 0/3 in C 验证. The fix uses mandatory phrasing in two layers:
    prompt step 0 + each補齐 skill's query-pattern intro line.
    """

    def test_prompt_step_0_mandates_literal_skill_templates(self):
        from deep_research.prompts import (
            research_agent_prompt_with_skills,
        )

        # Sentinel phrase added to step 0. If a future refactor renames the
        # phrasing, update this assertion deliberately rather than删 the test.
        self.assertIn(
            "首次 tavily_search 必须直接复用 skill",
            research_agent_prompt_with_skills,
            "step 0 should mandate literal reuse of loaded skill templates",
        )

    def test_each_补齐_skill_has_mandatory_query_pattern_intro(self):
        from deep_research.skills_loader import load_skill

        # academic-research was the reference skill from day one and intentionally
        # does not follow the mandatory-phrasing pattern; only the 3 补齐 skills do.
        for name in ("product-comparison", "news-timeline", "people-research"):
            body = load_skill.invoke({"skill_name": name})
            self.assertIn(
                "第一次搜索必须",
                body,
                f"{name} 「查询模式」段应使用必须性措辞 (Todo 2)",
            )


class CompressModelRetryTests(unittest.TestCase):
    """Todo 3: compress_model must self-heal transient 503s via .with_retry().

    Provider 在长 context (~50-100K token) compress 单步偶发返回 HTML 错误页, A
    任务 4 query 中 2 次 / B 验证 3/3 query 全部 503. retry 让短暂的 provider
    抖动可自愈, 不让一次失败拖垮整个 research 节点.
    """

    def test_compress_model_wrapped_with_retry(self):
        """Structural: production wiring uses langchain RunnableRetry, 3 attempts."""
        from langchain_core.runnables.retry import RunnableRetry

        from deep_research import research_agent_skills as mod

        self.assertIsInstance(
            mod.compress_model,
            RunnableRetry,
            "compress_model 应通过 .with_retry() 包成 RunnableRetry",
        )
        self.assertEqual(mod.compress_model.max_attempt_number, 3)
        self.assertTrue(mod.compress_model.wait_exponential_jitter)

    def test_retry_recovers_from_transient_error(self):
        """Behavioral: 第一次 invoke 抛 503, 第二次成功 → compress_research 拿到成功结果.

        换掉 mod.compress_model 为同样 .with_retry 包装的 flaky lambda
        (no jitter, instant retry), 确认 compress_research 走通整条调用链.
        """
        from langchain_core.runnables import RunnableLambda

        from deep_research import research_agent_skills as mod

        attempts = {"n": 0}
        fake_response = MagicMock()
        fake_response.content = "成功-在重试后"

        def flaky(_messages):
            attempts["n"] += 1
            if attempts["n"] == 1:
                # 模拟 provider 返回 HTML 错误页时 openai SDK 抛的 InternalServerError
                raise RuntimeError("503 InternalServerError")
            return fake_response

        flaky_model = RunnableLambda(flaky).with_retry(
            stop_after_attempt=3,
            wait_exponential_jitter=False,  # 单测不真等
        )

        with patch.object(mod, "compress_model", flaky_model):
            state = {
                "researcher_messages": [
                    HumanMessage(content="topic"),
                    # 需要至少一条真实 tavily_search 结果, 否则无结果防御会在
                    # 调用 compress_model 之前短路返回失败标记 (见 _has_real_search_results)。
                    ToolMessage(
                        content="1. Source: example.com — 真实搜索结果",
                        name="tavily_search",
                        tool_call_id="t1",
                    ),
                ],
            }
            result = mod.compress_research(state)

        self.assertEqual(attempts["n"], 2, "应在第二次尝试成功")
        self.assertEqual(result["compressed_research"], "成功-在重试后")


if __name__ == "__main__":
    unittest.main()
