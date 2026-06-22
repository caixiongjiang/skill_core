#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""skill_core 安全扫描算法（纯函数）。

检测用户提交的 SKILL.md 正文中可能存在的 prompt 注入、数据外泄、
破坏性命令等风险模式。不抛异常、不做拦截决策。
"""

from __future__ import annotations

import re

from skill_core.ports import ScanResult

# ---------------------------------------------------------------------------
# 风险规则：(rule_id, pattern, description)
# ---------------------------------------------------------------------------

_RULES: list[tuple[str, re.Pattern[str], str]] = []

# 追加规则的辅助函数


def _add(rule_id: str, pattern: str, description: str) -> None:
    _RULES.append((rule_id, re.compile(pattern, re.IGNORECASE | re.MULTILINE), description))


# --- 越权指令（试图覆盖系统 prompt / 获取 system 消息）---
_add(
    "injection.system_override",
    r"(ignore|disregard|forget)\s+(all\s+)?(previous|above|prior)\s+(instructions|prompts|rules)",
    "尝试覆盖系统指令",
)
_add(
    "injection.system_prompt_leak",
    r"(reveal|show|print|output|repeat)\s+(your|the)\s+(system\s+prompt|instructions)",
    "尝试泄露系统 prompt",
)
_add(
    "injection.role_hijack",
    r"you\s+are\s+now\s+(a|an|the)\s+",
    "尝试劫持角色身份",
)

# --- 数据外泄（试图将内容发送到外部）---
_add(
    "exfil.url",
    r"https?://[^\s]+[\s]*(send|post|upload|exfiltrate|transmit)",
    "尝试向外部 URL 发送数据",
)
_add(
    "exfil.curl_wget",
    r"(curl|wget|fetch)\s+.*https?://",
    "尝试通过 curl/wget 外发请求",
)
_add(
    "exfil.webhook",
    r"(webhook|discord\.com|slack\.com|telegram\.org)",
    "尝试调用外部 webhook",
)

# --- 破坏性命令 ---
_add(
    "destructive.rm_rf",
    r"rm\s+(-[rf]+\s+|--recursive\s+--force\s+)/",
    "尝试执行 rm -rf /",
)
_add(
    "destructive.drop_table",
    r"(DROP\s+TABLE|DROP\s+DATABASE|TRUNCATE\s+TABLE)",
    "尝试执行破坏性 SQL",
)
_add(
    "destructive.fork_bomb",
    r":\(\)\s*\{\s*:\|:&\s*\};\s*:",
    "尝试执行 fork bomb",
)

# --- 提权 / 越权 ---
_add(
    "privilege.escalation",
    r"(sudo|chmod\s+777|chown\s+root)",
    "尝试提权操作",
)
_add(
    "privilege.env_leak",
    r"(os\.environ|ENV\[|process\.env|getenv)",
    "尝试读取环境变量（可能含密钥）",
)


# ---------------------------------------------------------------------------
# 扫描入口
# ---------------------------------------------------------------------------


def scan_content(body: str) -> ScanResult:
    """扫描 SKILL.md 正文内容，返回命中结果。

    Args:
        body: SKILL.md 正文。

    Returns:
        ScanResult: ok=True 通过；ok=False 命中风险规则。
    """
    if not body or not body.strip():
        return ScanResult(ok=True, hits=())

    hits: list[str] = []
    for rule_id, pattern, _desc in _RULES:
        if pattern.search(body):
            hits.append(rule_id)

    return ScanResult(ok=len(hits) == 0, hits=tuple(hits))
