#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""skill_core 持久化端口与安全扫描接口。

Protocol 定义零 ORM 依赖的存储契约；ScanResult / scan_content 为安全扫描纯函数。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from skill_core.types import CustomSkillRecord


# ---------------------------------------------------------------------------
# 持久化端口
# ---------------------------------------------------------------------------


@runtime_checkable
class SkillRepository(Protocol):
    """技能持久化端口（零 ORM，由各后端注入具体实现）。"""

    def list_custom(self) -> list[CustomSkillRecord]:
        """列出所有自定义技能。"""
        ...

    def get(self, name: str) -> CustomSkillRecord | None:
        """按名称获取单个自定义技能。"""
        ...

    def create(self, rec: CustomSkillRecord) -> None:
        """创建自定义技能。"""
        ...

    def update(self, rec: CustomSkillRecord) -> None:
        """更新自定义技能。"""
        ...

    def delete(self, name: str) -> None:
        """删除自定义技能。"""
        ...

    def get_states(self) -> dict[str, bool]:
        """获取所有技能的启用状态 {name: enabled}。"""
        ...

    def set_state(self, name: str, enabled: bool) -> None:
        """设置技能启用/停用状态。"""
        ...

    def table_version(self) -> int:
        """返回自定义技能表的版本号（每次 CRUD 递增），供 registry 失效键。"""
        ...


# ---------------------------------------------------------------------------
# 安全扫描
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScanResult:
    """安全扫描结果。"""

    ok: bool
    hits: tuple[str, ...]  # 命中的风险规则（空 = 通过）


def scan_content(body: str) -> ScanResult:
    """内容安全扫描算法（纯函数）。

    检测 prompt 注入、数据外泄、破坏性命令等风险模式。
    不抛异常、不做拦截决策——由调用方（SkillService）根据结果决定告警/拦截。

    Args:
        body: SKILL.md 正文内容。

    Returns:
        ScanResult: ok=True 表示通过，ok=False 表示命中风险规则。
    """
    from skill_core.security import scan_content as _scan

    return _scan(body)
