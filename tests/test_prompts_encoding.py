"""Regression tests for prompt content and source encoding."""

from pathlib import Path
import unittest

from deep_research import prompts


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROMPTS_PATH = PROJECT_ROOT / "src" / "deep_research" / "prompts.py"


class PromptsEncodingTests(unittest.TestCase):
    def test_prompts_source_can_be_read_with_utf8(self) -> None:
        """Ensure the source file remains readable with the project encoding."""
        source = PROMPTS_PATH.read_text(encoding="utf-8")
        self.assertIn('clarify_with_user_instructions = """', source)

    def test_clarify_prompt_keeps_chinese_runtime_text(self) -> None:
        self.assertIn("以下是用户请求报告过程中的对话记录：", prompts.clarify_with_user_instructions)
        self.assertIn("今天的日期是 {date}。", prompts.clarify_with_user_instructions)

    def test_clarify_prompt_contains_complete_json_object_examples(self) -> None:
        prompt = prompts.clarify_with_user_instructions
        self.assertIn("请仅返回一个 JSON 对象", prompt)
        self.assertIn('{{\n  "need_clarification": boolean,', prompt)
        self.assertIn('{{\n  "need_clarification": true,', prompt)
        self.assertIn('{{\n  "need_clarification": false,', prompt)


if __name__ == "__main__":
    unittest.main()
