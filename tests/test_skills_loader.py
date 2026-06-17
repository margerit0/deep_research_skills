"""Tests for deep_research.skills_loader."""

import unittest
import unittest.mock
from pathlib import Path
from tempfile import TemporaryDirectory


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


VALID_FRONTMATTER = (
    "name: foo\n"
    "description: 描述 foo\n"
    "when_to_use: 当遇到 foo 时\n"
)


class ScanSkillsTests(unittest.TestCase):
    def test_scan_valid_skill(self):
        from deep_research.skills_loader import _scan_skills

        with TemporaryDirectory() as td:
            tmp = Path(td)
            _write(
                tmp / "foo.md",
                f"---\n{VALID_FRONTMATTER}---\n# foo\n\n正文内容\n",
            )
            metadata, body = _scan_skills(tmp)

        self.assertEqual(len(metadata), 1)
        self.assertEqual(metadata[0]["name"], "foo")
        self.assertEqual(metadata[0]["description"], "描述 foo")
        self.assertEqual(metadata[0]["when_to_use"], "当遇到 foo 时")
        self.assertIn("正文内容", body["foo"])
        self.assertNotIn("description: 描述 foo", body["foo"])

    def test_when_to_use_optional(self):
        from deep_research.skills_loader import _scan_skills

        with TemporaryDirectory() as td:
            tmp = Path(td)
            _write(
                tmp / "foo.md",
                "---\nname: foo\ndescription: 描述\n---\n正文\n",
            )
            metadata, body = _scan_skills(tmp)

        self.assertEqual(len(metadata), 1)
        self.assertEqual(metadata[0]["when_to_use"], "")
        self.assertIn("正文", body["foo"])

    def test_skip_missing_frontmatter(self):
        from deep_research.skills_loader import _scan_skills

        with TemporaryDirectory() as td:
            tmp = Path(td)
            _write(tmp / "foo.md", "纯 markdown 无 frontmatter\n")
            metadata, body = _scan_skills(tmp)

        self.assertEqual(metadata, [])
        self.assertEqual(body, {})

    def test_skip_missing_required_field(self):
        from deep_research.skills_loader import _scan_skills

        with TemporaryDirectory() as td:
            tmp = Path(td)
            _write(tmp / "foo.md", "---\nname: foo\n---\n正文\n")  # 缺 description
            metadata, body = _scan_skills(tmp)

        self.assertEqual(metadata, [])

    def test_skip_malformed_yaml(self):
        from deep_research.skills_loader import _scan_skills

        with TemporaryDirectory() as td:
            tmp = Path(td)
            _write(
                tmp / "foo.md",
                "---\nname: foo\n  bad: indent: here\n---\n正文\n",
            )
            metadata, body = _scan_skills(tmp)

        self.assertEqual(metadata, [])

    def test_skip_name_filename_mismatch(self):
        from deep_research.skills_loader import _scan_skills

        with TemporaryDirectory() as td:
            tmp = Path(td)
            _write(
                tmp / "bar.md",
                "---\nname: foo\ndescription: 描述\n---\n正文\n",
            )
            metadata, body = _scan_skills(tmp)

        self.assertEqual(metadata, [])

    def test_skills_dir_missing_raises(self):
        from deep_research.skills_loader import _scan_skills

        with TemporaryDirectory() as td:
            missing = Path(td) / "does_not_exist"
            with self.assertRaises(FileNotFoundError):
                _scan_skills(missing)

    def test_returns_skills_sorted_by_name(self):
        from deep_research.skills_loader import _scan_skills

        with TemporaryDirectory() as td:
            tmp = Path(td)
            _write(tmp / "b.md", "---\nname: b\ndescription: B\n---\n")
            _write(tmp / "a.md", "---\nname: a\ndescription: A\n---\n")
            metadata, _ = _scan_skills(tmp)

        self.assertEqual([m["name"] for m in metadata], ["a", "b"])


class FormatSkillsIndexTests(unittest.TestCase):
    def test_includes_all_skills(self):
        from deep_research import skills_loader

        with unittest.mock.patch.object(
            skills_loader,
            "SKILLS_METADATA",
            [
                {"name": "alpha", "description": "alpha 描述", "when_to_use": ""},
                {"name": "beta", "description": "beta 描述", "when_to_use": ""},
            ],
        ):
            out = skills_loader.format_skills_index()

        self.assertIn("alpha", out)
        self.assertIn("alpha 描述", out)
        self.assertIn("beta", out)
        self.assertIn("beta 描述", out)

    def test_empty_returns_placeholder(self):
        from deep_research import skills_loader

        with unittest.mock.patch.object(skills_loader, "SKILLS_METADATA", []):
            out = skills_loader.format_skills_index()

        self.assertTrue(out)  # 非空字符串
        self.assertNotIn("alpha", out)


class LoadSkillToolTests(unittest.TestCase):
    def test_load_skill_known_returns_body(self):
        from deep_research import skills_loader

        with unittest.mock.patch.object(
            skills_loader,
            "SKILLS_BODY",
            {"foo": "# foo\n\n正文内容"},
        ):
            out = skills_loader.load_skill.invoke({"skill_name": "foo"})

        self.assertEqual(out, "# foo\n\n正文内容")

    def test_load_skill_unknown_returns_error_with_available(self):
        from deep_research import skills_loader

        with unittest.mock.patch.object(
            skills_loader,
            "SKILLS_BODY",
            {"foo": "F", "bar": "B"},
        ):
            out = skills_loader.load_skill.invoke({"skill_name": "missing"})

        self.assertIn("missing", out)
        self.assertIn("不存在", out)
        self.assertIn("foo", out)
        self.assertIn("bar", out)


if __name__ == "__main__":
    unittest.main()
