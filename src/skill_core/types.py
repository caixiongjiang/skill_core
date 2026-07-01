#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""skill_core 领域类型定义。

所有类型均为 frozen dataclass，零 ORM / 零 agent 框架依赖。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class SkillDescriptor:
    """技能元数据描述符（Level 0 索引用）。"""

    name: str
    description: str
    category: str
    tags: tuple[str, ...]
    version: str
    requires_tools: tuple[str, ...]
    fallback_for_tools: tuple[str, ...]
    source: str  # "builtin" | "custom"
    enabled: bool
    deletable: bool  # = (source == "custom")；内置技能不可删
    path: Path | None  # builtin: SKILL.md 路径; custom: None


@dataclass(frozen=True)
class Skill:
    """完整技能对象（Level 1 含正文，Level 2 含附件列表）。"""

    descriptor: SkillDescriptor
    body: str  # SKILL.md 正文（Level 1）
    files: tuple[str, ...]  # 可加载的附件相对路径（Level 2，仅 builtin）


@dataclass(frozen=True)
class CustomSkillRecord:
    """自定义技能的 DB 行传输对象（持久化端口用，零 ORM）。"""

    name: str
    description: str
    category: str
    tags: tuple[str, ...]
    version: str
    requires_tools: tuple[str, ...]
    fallback_for_tools: tuple[str, ...]
    body: str  # 完整 SKILL.md 正文
    created_by: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ParsedSkill:
    """从 SKILL.md 解析出的原始数据（loader 输出）。"""

    name: str
    description: str
    category: str
    tags: tuple[str, ...]
    version: str
    requires_tools: tuple[str, ...]
    fallback_for_tools: tuple[str, ...]
    body: str  # 完整正文（含 frontmatter 或纯 body）
    frontmatter: dict  # 原始 frontmatter 字典
