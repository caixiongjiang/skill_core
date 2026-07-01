#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""skill_core 默认 MySQL 持久化适配。

实现 SkillRepository 端口，session/连接由调用方注入。
自带 skill / skill_state 表 DDL（schema 单一所有者）。
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Callable, Generator

from loguru import logger
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Session, declarative_base

from skill_core.ports import SkillRepository
from skill_core.types import CustomSkillRecord

Base = declarative_base()


# ---------------------------------------------------------------------------
# ORM 模型（仅供本适配器内部使用，外部不得 import）
# ---------------------------------------------------------------------------


class SkillModel(Base):
    """自定义技能表。"""

    __tablename__ = "skill"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(64), unique=True, nullable=False, comment="技能名，全局唯一")
    description = Column(String(1024), nullable=False, comment="技能描述")
    category = Column(String(64), default="custom", comment="技能类别")
    tags = Column(Text, comment="标签 JSON 数组")
    version = Column(String(32), default="1.0.0", comment="版本号")
    requires_tools = Column(Text, comment="依赖工具 JSON 数组")
    fallback_for_tools = Column(Text, comment="降级工具 JSON 数组")
    body = Column(Text, nullable=False, comment="SKILL.md 正文")
    created_by = Column(String(64), comment="创建者 user_id")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")


class SkillStateModel(Base):
    """技能启停状态表（builtin + custom 统一）。"""

    __tablename__ = "skill_state"

    name = Column(String(64), primary_key=True, comment="技能名")
    enabled = Column(Boolean, default=True, comment="是否启用")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")


# ---------------------------------------------------------------------------
# 版本号表（供 registry 失效键）
# ---------------------------------------------------------------------------


class SkillVersionModel(Base):
    """技能版本号表（单行，记录自定义技能表的变更次数）。"""

    __tablename__ = "skill_version"

    id = Column(Integer, primary_key=True, default=1)
    version = Column(Integer, default=0, nullable=False, comment="版本号，每次 CRUD 递增")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

SKILL_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS skill (
    id           BIGINT PRIMARY KEY AUTO_INCREMENT,
    name         VARCHAR(64) UNIQUE NOT NULL COMMENT '技能名，全局唯一',
    description  VARCHAR(1024) NOT NULL COMMENT '技能描述',
    category     VARCHAR(64) DEFAULT 'custom' COMMENT '技能类别',
    tags         JSON COMMENT '标签 JSON 数组',
    version      VARCHAR(32) DEFAULT '1.0.0' COMMENT '版本号',
    requires_tools JSON COMMENT '依赖工具 JSON 数组',
    fallback_for_tools JSON COMMENT '降级工具 JSON 数组',
    body         MEDIUMTEXT NOT NULL COMMENT 'SKILL.md 正文',
    created_by   VARCHAR(64) COMMENT '创建者 user_id',
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

SKILL_STATE_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS skill_state (
    name        VARCHAR(64) PRIMARY KEY COMMENT '技能名',
    enabled     BOOLEAN DEFAULT TRUE COMMENT '是否启用',
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

SKILL_VERSION_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS skill_version (
    id          INT PRIMARY KEY DEFAULT 1,
    version     INT DEFAULT 0 NOT NULL COMMENT '版本号',
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

# 旧库增量迁移（CREATE TABLE IF NOT EXISTS 不会补列）
SKILL_TABLE_ALTER_DDL = [
    """
    ALTER TABLE skill
    ADD COLUMN fallback_for_tools JSON NULL
    COMMENT '降级工具 JSON 数组'
    AFTER requires_tools
    """,
]


# ---------------------------------------------------------------------------
# Repository 实现
# ---------------------------------------------------------------------------

SessionFactory = Callable[[], Session]


class MySQLSkillRepository:
    """MySQL 持久化适配（实现 SkillRepository 端口）。

    session_factory 由调用方注入（如 get_mysql_manager().get_session）。
    """

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    # ------------------------------------------------------------------
    # Schema 初始化
    # ------------------------------------------------------------------

    def ensure_tables(self) -> None:
        """确保 skill / skill_state / skill_version 表存在。"""
        session = self._session_factory()
        try:
            session.execute(text(SKILL_TABLE_DDL))
            session.execute(text(SKILL_STATE_TABLE_DDL))
            session.execute(text(SKILL_VERSION_TABLE_DDL))
            for alter_sql in SKILL_TABLE_ALTER_DDL:
                try:
                    session.execute(text(alter_sql))
                except Exception as e:
                    # 1060: Duplicate column name — 列已存在则忽略
                    if "Duplicate column name" not in str(e):
                        raise
            # 确保 version 表有初始行
            existing = session.query(SkillVersionModel).first()
            if existing is None:
                session.add(SkillVersionModel(id=1, version=0))
            session.commit()
            logger.info("skill 相关表已就绪")
        except Exception as e:
            session.rollback()
            logger.error(f"创建 skill 表失败: {e}")
            raise
        finally:
            session.close()

    # ------------------------------------------------------------------
    # SkillRepository 接口实现
    # ------------------------------------------------------------------

    def list_custom(self) -> list[CustomSkillRecord]:
        session = self._session_factory()
        try:
            rows = session.query(SkillModel).all()
            return [self._row_to_record(row) for row in rows]
        finally:
            session.close()

    def get(self, name: str) -> CustomSkillRecord | None:
        session = self._session_factory()
        try:
            row = session.query(SkillModel).filter(SkillModel.name == name).first()
            return self._row_to_record(row) if row else None
        finally:
            session.close()

    def create(self, rec: CustomSkillRecord) -> None:
        session = self._session_factory()
        try:
            row = SkillModel(
                name=rec.name,
                description=rec.description,
                category=rec.category,
                tags=json.dumps(list(rec.tags), ensure_ascii=False) if rec.tags else None,
                version=rec.version,
                requires_tools=json.dumps(list(rec.requires_tools), ensure_ascii=False) if rec.requires_tools else None,
                body=rec.body,
                created_by=rec.created_by,
                created_at=rec.created_at,
                updated_at=rec.updated_at,
            )
            session.add(row)
            self._bump_version(session)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def update(self, rec: CustomSkillRecord) -> None:
        session = self._session_factory()
        try:
            row = session.query(SkillModel).filter(SkillModel.name == rec.name).first()
            if row is None:
                raise ValueError(f"技能 '{rec.name}' 不存在")

            row.description = rec.description
            row.category = rec.category
            tags=json.dumps(list(rec.tags), ensure_ascii=False) if rec.tags else None
            row.tags = tags
            row.version = rec.version
            row.requires_tools = (
                json.dumps(list(rec.requires_tools), ensure_ascii=False)
                if rec.requires_tools
                else None
            )
            row.body = rec.body
            row.updated_at = rec.updated_at

            self._bump_version(session)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def delete(self, name: str) -> None:
        session = self._session_factory()
        try:
            row = session.query(SkillModel).filter(SkillModel.name == name).first()
            if row is None:
                raise ValueError(f"技能 '{name}' 不存在")

            session.delete(row)
            # 同时清理 skill_state
            state_row = session.query(SkillStateModel).filter(
                SkillStateModel.name == name
            ).first()
            if state_row:
                session.delete(state_row)

            self._bump_version(session)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_states(self) -> dict[str, bool]:
        session = self._session_factory()
        try:
            rows = session.query(SkillStateModel).all()
            return {row.name: row.enabled for row in rows}
        finally:
            session.close()

    def set_state(self, name: str, enabled: bool) -> None:
        session = self._session_factory()
        try:
            row = session.query(SkillStateModel).filter(
                SkillStateModel.name == name
            ).first()
            if row:
                row.enabled = enabled
                row.updated_at = datetime.now()
            else:
                session.add(SkillStateModel(
                    name=name,
                    enabled=enabled,
                    updated_at=datetime.now(),
                ))
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def table_version(self) -> int:
        session = self._session_factory()
        try:
            row = session.query(SkillVersionModel).first()
            return row.version if row else 0
        finally:
            session.close()

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_record(row: SkillModel) -> CustomSkillRecord:
        """将 ORM 行转为 CustomSkillRecord。"""
        return CustomSkillRecord(
            name=row.name,
            description=row.description,
            category=row.category,
            tags=tuple(json.loads(row.tags)) if row.tags else (),
            version=row.version,
            requires_tools=tuple(json.loads(row.requires_tools)) if row.requires_tools else (),
            fallback_for_tools=(),
            body=row.body,
            created_by=row.created_by or "",
            created_at=row.created_at or datetime.now(),
            updated_at=row.updated_at or datetime.now(),
        )

    @staticmethod
    def _bump_version(session: Session) -> None:
        """递增版本号。"""
        session.execute(
            text("UPDATE skill_version SET version = version + 1 WHERE id = 1")
        )
