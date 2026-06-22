#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""skill_core 技能注册表。

进程内单例，合并内置（磁盘）+ 自定义（DB via repository）两个来源，
提供 Level-0 索引构建、技能正文读取、缓存失效等能力。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from skill_core.loader import (
    load_builtin_skill,
    read_builtin_file,
    scan_builtin_skills,
)
from skill_core.ports import SkillRepository
from skill_core.types import CustomSkillRecord, Skill, SkillDescriptor


class SkillRegistry:
    """技能注册表：合并 builtin + custom，提供索引构建与技能读取。

    通过依赖注入拿 repository，自身绝不直接连库。
    """

    def __init__(self, builtin_dir: Path, repo: SkillRepository) -> None:
        self._builtin_dir = builtin_dir
        self._repo = repo

        # 缓存
        self._builtin_descriptors: list[SkillDescriptor] | None = None
        self._cache_key: tuple[Any, ...] | None = None
        self._index_cache: str = ""

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def list_descriptors(
        self, *, include_disabled: bool = False
    ) -> list[SkillDescriptor]:
        """列出所有技能 descriptor（builtin + custom 合并）。"""
        all_desc = self._get_all_descriptors()
        if include_disabled:
            return list(all_desc)
        return [d for d in all_desc if d.enabled]

    def get(self, name: str) -> Skill | None:
        """按名称获取完整技能对象（含正文）。"""
        # 先查 builtin
        for desc in self._get_builtin_descriptors():
            if desc.name == name:
                return load_builtin_skill(desc)

        # 再查 custom
        rec = self._repo.get(name)
        if rec is not None:
            desc = self._custom_record_to_descriptor(rec, enabled=True)
            return Skill(descriptor=desc, body=rec.body, files=())

        # 检查是否在 skill_state 中存在（可能是停用的 builtin）
        states = self._repo.get_states()
        if name in states:
            # 重新查 builtin（可能被 enabled=False 过滤掉了）
            for desc in self._get_builtin_descriptors():
                if desc.name == name:
                    return load_builtin_skill(desc)

        return None

    def get_file(self, name: str, rel_path: str) -> str | None:
        """读取技能的附带文件（Level 2，带路径穿越防护）。"""
        # builtin 技能才有附件
        for desc in self._get_builtin_descriptors():
            if desc.name == name:
                return read_builtin_file(desc, rel_path)
        return None

    def build_index(self, enabled_tools: set[str]) -> str:
        """构建 Level-0 技能索引文本块（注入 system prompt）。

        逻辑：
        1. 取 list_descriptors()。
        2. 条件激活过滤（requires_tools / fallback_for_tools）。
        3. 按 category 分组渲染。
        4. 结果带缓存。

        Args:
            enabled_tools: 当前启用的工具名集合。

        Returns:
            渲染后的索引文本块。
        """
        cache_key = self._make_cache_key(enabled_tools)
        if cache_key == self._cache_key and self._index_cache:
            return self._index_cache

        descriptors = self.list_descriptors()

        # 条件激活过滤
        filtered = [
            d
            for d in descriptors
            if self._should_show(d, enabled_tools)
        ]

        # 按 category 分组
        groups: dict[str, list[SkillDescriptor]] = {}
        for d in filtered:
            groups.setdefault(d.category, []).append(d)

        # 渲染
        lines = [
            "## 技能（强制扫描）",
            "回答前必须扫描下列技能。若某技能与当前任务相关（哪怕部分相关），你**必须**用",
            '`skill_view(name="<技能名>")` 加载其完整指令并严格遵循。宁可多加载，也不要漏掉',
            "关键步骤、坑位或既定流程。仅当确实无任何技能相关时，才直接作答。",
            "",
            "<available_skills>",
        ]

        for category in sorted(groups):
            lines.append(f"  {category}:")
            for d in groups[category]:
                lines.append(f"    - {d.name}: {d.description}")

        lines.append("</available_skills>")
        lines.append("")

        index_text = "\n".join(lines)

        # 更新缓存
        self._cache_key = cache_key
        self._index_cache = index_text

        logger.debug(
            f"技能索引已构建: {len(filtered)}/{len(descriptors)} 个技能, "
            f"cache_key={cache_key}"
        )
        return index_text

    def invalidate(self) -> None:
        """使缓存失效（自定义技能 CRUD 后调用）。"""
        self._builtin_descriptors = None
        self._cache_key = None
        self._index_cache = ""
        logger.debug("技能注册表缓存已失效")

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _get_builtin_descriptors(self) -> list[SkillDescriptor]:
        """获取内置技能 descriptor（带缓存）。"""
        if self._builtin_descriptors is None:
            self._builtin_descriptors = scan_builtin_skills(self._builtin_dir)
        return self._builtin_descriptors

    def _get_all_descriptors(self) -> list[SkillDescriptor]:
        """合并 builtin + custom descriptor，并应用 skill_state。"""
        states = self._repo.get_states()

        result: list[SkillDescriptor] = []

        # builtin
        for desc in self._get_builtin_descriptors():
            enabled = states.get(desc.name, True)  # 默认启用
            if desc.enabled != enabled:
                desc = SkillDescriptor(
                    name=desc.name,
                    description=desc.description,
                    category=desc.category,
                    tags=desc.tags,
                    version=desc.version,
                    requires_tools=desc.requires_tools,
                    fallback_for_tools=desc.fallback_for_tools,
                    source=desc.source,
                    enabled=enabled,
                    deletable=desc.deletable,
                    path=desc.path,
                )
            result.append(desc)

        # custom
        for rec in self._repo.list_custom():
            enabled = states.get(rec.name, True)
            result.append(self._custom_record_to_descriptor(rec, enabled=enabled))

        return result

    @staticmethod
    def _custom_record_to_descriptor(
        rec: CustomSkillRecord, *, enabled: bool
    ) -> SkillDescriptor:
        """将 CustomSkillRecord 转为 SkillDescriptor。"""
        return SkillDescriptor(
            name=rec.name,
            description=rec.description,
            category=rec.category,
            tags=rec.tags,
            version=rec.version,
            requires_tools=rec.requires_tools,
            fallback_for_tools=rec.fallback_for_tools,
            source="custom",
            enabled=enabled,
            deletable=True,
            path=None,
        )

    @staticmethod
    def _should_show(desc: SkillDescriptor, enabled_tools: set[str]) -> bool:
        """判断技能是否应出现在索引中（条件激活）。"""
        # requires_tools: 必须全在 enabled_tools 内
        if desc.requires_tools:
            missing = set(desc.requires_tools) - enabled_tools
            if missing:
                return False

        # fallback_for_tools: 任一在则隐藏
        if desc.fallback_for_tools:
            if any(t in enabled_tools for t in desc.fallback_for_tools):
                return False

        return True

    def _make_cache_key(self, enabled_tools: set[str]) -> tuple[Any, ...]:
        """构建缓存键。"""
        # builtin 目录指纹：各 SKILL.md 的 mtime/size 聚合
        builtin_fingerprint = self._builtin_fingerprint()
        # 自定义技能表版本号
        table_ver = self._repo.table_version()
        return (builtin_fingerprint, table_ver, frozenset(enabled_tools))

    def _builtin_fingerprint(self) -> str:
        """计算内置目录指纹（各 SKILL.md 的 mtime+size）。"""
        parts: list[str] = []
        for desc in self._get_builtin_descriptors():
            if desc.path and desc.path.is_file():
                stat = desc.path.stat()
                parts.append(f"{desc.name}:{stat.st_mtime}:{stat.st_size}")
        return "|".join(sorted(parts))
