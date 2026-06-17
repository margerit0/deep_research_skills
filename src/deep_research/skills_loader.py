"""Markdown 研究方法论 skills 的加载器。

在 import 时扫描 ``skills/*.md`` 文件，并对外暴露：

- ``SKILLS_METADATA`` / ``SKILLS_BODY``：模块级快照，从包内的
  ``skills/`` 目录填充（在后续步骤中加入）。
- ``_scan_skills(skills_dir)``：底层辅助函数，供使用 ``tmp_path``
  fixture 的测试调用，使测试不依赖真实的 skills 目录。

每个 skill 都是一个带 YAML frontmatter 的 markdown 文件::

    ---
    name: academic-research
    description: ...
    when_to_use: ...   # optional
    ---
    <markdown body>

``name`` 字段必须与文件名主干 (stem) 一致（例如 ``academic-research.md``
中必须写 ``name: academic-research``）；这条不变式 (invariant) 使得
只要文件名唯一，就足以保证 skill 名唯一。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Tuple

import frontmatter
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = ("name", "description")


def _scan_skills(skills_dir: Path) -> Tuple[List[dict], Dict[str, str]]:
    """扫描 ``skills_dir`` 目录下的 markdown skills。

    Args:
        skills_dir: 存放 ``*.md`` skill 文件的目录。

    Returns:
        (metadata_list, body_dict)。``metadata_list`` 按 name 排序，
        每个条目包含 ``name`` / ``description`` / ``when_to_use`` 三个键
        （最后一项默认为 ``""``）。``body_dict`` 将 name 映射到 markdown
        正文（已剥离 frontmatter）。

    Raises:
        FileNotFoundError: ``skills_dir`` 不存在或不是目录。
    """
    if not skills_dir.exists() or not skills_dir.is_dir():
        raise FileNotFoundError(f"Skills directory not found: {skills_dir}")

    metadata_list: List[dict] = []
    body_dict: Dict[str, str] = {}

    for md_path in sorted(skills_dir.glob("*.md")):
        try:
            post = frontmatter.load(md_path)
        except Exception as exc:  # noqa: BLE001 — frontmatter raises various YAML errors
            logger.warning(
                "Skipping skill %s: failed to parse frontmatter (%s: %s)",
                md_path.name,
                type(exc).__name__,
                exc,
            )
            continue

        meta = post.metadata or {}
        missing = [f for f in REQUIRED_FIELDS if not meta.get(f)]
        if missing:
            logger.warning(
                "Skipping skill %s: missing required field(s) %s",
                md_path.name,
                missing,
            )
            continue

        name = meta["name"]
        if name != md_path.stem:
            logger.warning(
                "Skipping skill %s: frontmatter name %r does not match filename stem %r",
                md_path.name,
                name,
                md_path.stem,
            )
            continue

        metadata_list.append(
            {
                "name": name,
                "description": meta["description"],
                "when_to_use": meta.get("when_to_use", "") or "",
            }
        )
        body_dict[name] = post.content

    return metadata_list, body_dict


# ===== 模块级快照，在 import 时填充 (Module-level snapshot, populated at import time) =====

_DEFAULT_SKILLS_DIR = Path(__file__).parent / "skills"
SKILLS_METADATA, SKILLS_BODY = _scan_skills(_DEFAULT_SKILLS_DIR)


def format_skills_index() -> str:
    """将 SKILLS_METADATA 格式化为项目符号列表，用于注入系统提示词 (system prompt)。"""
    if not SKILLS_METADATA:
        return "(当前没有可用 skill)"
    return "\n".join(
        f"- **{m['name']}**: {m['description']}" for m in SKILLS_METADATA
    )


@tool(parse_docstring=True)
def load_skill(skill_name: str) -> str:
    """加载指定 skill 的研究方法论正文。

    Args:
        skill_name: skill 名（从 <Available Skills> 列表中选）。

    Returns:
        skill 的 markdown 正文；若 name 未找到则返回错误说明 + 可用 skill 清单。
    """
    if skill_name not in SKILLS_BODY:
        available = ", ".join(sorted(SKILLS_BODY)) or "(无)"
        return (
            f"错误：skill '{skill_name}' 不存在。"
            f"可用 skill：{available}。请从中选择并重试。"
        )
    return SKILLS_BODY[skill_name]
