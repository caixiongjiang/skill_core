#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""skill_core 内置技能加载器。

扫描磁盘 skills/ 目录，解析 SKILL.md frontmatter（CSafeLoader + 容错回退），
读取正文与附件列表。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from loguru import logger

from skill_core.types import ParsedSkill, SkillDescriptor, Skill


# ---------------------------------------------------------------------------
# Frontmatter 解析
# ---------------------------------------------------------------------------


def _parse_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    """解析 YAML frontmatter，返回 (frontmatter_dict, body)。

    容错策略（对齐 Hermes skill_utils.parse_frontmatter）：
    1. 尝试 CSafeLoader 解析完整 YAML；
    2. 失败则回退到逐行 key:value 简析；
    3. 仍失败则返回空 dict，全文作为 body。
    """
    if not raw.startswith("---"):
        return {}, raw

    # 找第二个 ---
    end = raw.find("---", 3)
    if end == -1:
        return {}, raw

    fm_text = raw[3:end].strip()
    body = raw[end + 3 :].strip()

    # 1. 尝试 CSafeLoader
    try:
        from yaml import CSafeLoader, load as yaml_load

        fm_dict = yaml_load(fm_text, Loader=CSafeLoader)
        if isinstance(fm_dict, dict):
            return fm_dict, body
    except Exception:
        pass

    # 2. 回退到逐行 key:value 简析
    fm_dict: dict[str, Any] = {}
    for line in fm_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            # 简单处理列表格式 [a, b, c]
            if value.startswith("[") and value.endswith("]"):
                value = [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]
            fm_dict[key] = value

    return fm_dict, body


def _extract_nested(fm: dict, *keys: str, default: Any = None) -> Any:
    """从嵌套 dict 中提取值，支持 metadata.tags 等路径。"""
    current = fm
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key, default)
        else:
            return default
    return current if current is not None else default


def _ensure_tuple(value: Any) -> tuple[str, ...]:
    """将值转为 tuple[str, ...]。"""
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    return (str(value),)


# ---------------------------------------------------------------------------
# 解析 SKILL.md
# ---------------------------------------------------------------------------


def parse_skill_md(raw: str) -> ParsedSkill:
    """解析 SKILL.md 原始文本，返回 ParsedSkill。

    Args:
        raw: SKILL.md 完整内容（含 frontmatter）。

    Returns:
        ParsedSkill: 解析后的技能数据。

    Raises:
        ValueError: frontmatter 缺少必填字段 name 或 description。
    """
    fm, body = _parse_frontmatter(raw)

    name = fm.get("name", "")
    description = fm.get("description", "")

    if not name:
        # 尝试从 body 第一个标题提取
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("# "):
                name = line[2:].strip().lower().replace(" ", "-")
                break
    if not name:
        raise ValueError("SKILL.md 缺少必填字段 'name'（frontmatter 或 body 标题）")

    if not description:
        raise ValueError(f"技能 '{name}' 缺少必填字段 'description'")

    return ParsedSkill(
        name=str(name).strip(),
        description=str(description).strip(),
        category=str(_extract_nested(fm, "metadata", "category", default="custom")),
        tags=_ensure_tuple(_extract_nested(fm, "metadata", "tags")),
        version=str(fm.get("version", "1.0.0")),
        requires_tools=_ensure_tuple(_extract_nested(fm, "metadata", "requires_tools")),
        fallback_for_tools=_ensure_tuple(_extract_nested(fm, "metadata", "fallback_for_tools")),
        body=raw,  # 保存完整内容（含 frontmatter）
        frontmatter=fm,
    )


# ---------------------------------------------------------------------------
# 扫描内置技能目录
# ---------------------------------------------------------------------------


def scan_builtin_skills(builtin_dir: Path) -> list[SkillDescriptor]:
    """扫描磁盘 skills/ 目录，返回所有内置技能的 descriptor。

    目录结构：skills/<category>/<name>/SKILL.md

    Args:
        builtin_dir: 技能根目录路径（如 ./skills）。

    Returns:
        内置技能 descriptor 列表。
    """
    descriptors: list[SkillDescriptor] = []

    if not builtin_dir.is_dir():
        logger.warning(f"内置技能目录不存在: {builtin_dir}")
        return descriptors

    for category_dir in sorted(builtin_dir.iterdir()):
        if not category_dir.is_dir() or category_dir.name.startswith((".", "_")):
            continue

        for skill_dir in sorted(category_dir.iterdir()):
            if not skill_dir.is_dir() or skill_dir.name.startswith((".", "_")):
                continue

            skill_md = skill_dir / "SKILL.md"
            if not skill_md.is_file():
                logger.debug(f"跳过无 SKILL.md 的目录: {skill_dir}")
                continue

            try:
                raw = skill_md.read_text(encoding="utf-8")
                parsed = parse_skill_md(raw)

                # 收集附件文件（排除 SKILL.md 本身）
                files = _collect_files(skill_dir)

                descriptors.append(
                    SkillDescriptor(
                        name=parsed.name,
                        description=parsed.description,
                        category=category_dir.name,
                        tags=parsed.tags,
                        version=parsed.version,
                        requires_tools=parsed.requires_tools,
                        fallback_for_tools=parsed.fallback_for_tools,
                        source="builtin",
                        enabled=True,  # 默认启用，实际状态由 skill_state 表控制
                        deletable=False,
                        path=skill_md,
                    )
                )
            except Exception as e:
                logger.error(f"解析内置技能失败 {skill_md}: {e}")

    return descriptors


def load_builtin_skill(descriptor: SkillDescriptor) -> Skill | None:
    """加载内置技能的完整内容（正文 + 附件列表）。

    Args:
        descriptor: 内置技能的 descriptor（path 必须非 None）。

    Returns:
        Skill 对象，加载失败返回 None。
    """
    if descriptor.path is None or not descriptor.path.is_file():
        logger.error(f"内置技能文件不存在: {descriptor.path}")
        return None

    try:
        body = descriptor.path.read_text(encoding="utf-8")
        files = _collect_files(descriptor.path.parent)
        return Skill(descriptor=descriptor, body=body, files=tuple(files))
    except Exception as e:
        logger.error(f"加载内置技能失败 {descriptor.name}: {e}")
        return None


def read_builtin_file(descriptor: SkillDescriptor, rel_path: str) -> str | None:
    """读取内置技能目录下的附件文件（带路径穿越防护）。

    Args:
        descriptor: 内置技能 descriptor。
        rel_path: 相对文件路径（如 "templates/report-outline.md"）。

    Returns:
        文件内容，不存在或路径非法返回 None。
    """
    if descriptor.path is None:
        return None

    skill_dir = descriptor.path.parent
    target = (skill_dir / rel_path).resolve()

    # 路径穿越防护
    if not str(target).startswith(str(skill_dir.resolve())):
        logger.warning(f"路径穿越尝试: {rel_path}")
        return None

    if not target.is_file():
        return None

    try:
        return target.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"读取附件失败 {rel_path}: {e}")
        return None


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _collect_files(skill_dir: Path) -> list[str]:
    """收集技能目录下除 SKILL.md 外的所有文件（相对路径列表）。"""
    files: list[str] = []
    for root, _dirs, filenames in os.walk(skill_dir):
        for fname in filenames:
            if fname.startswith(".") or fname == "SKILL.md":
                continue
            full = Path(root) / fname
            files.append(str(full.relative_to(skill_dir)))
    return sorted(files)
