"""skill_core — 技能系统核心包（runtime / ORM 无关，多后端复用）。

本包提供：
- 领域类型：SkillDescriptor / Skill / CustomSkillRecord / ParsedSkill
- 持久化端口：SkillRepository（Protocol）
- 安全扫描：scan_content / ScanResult
- 加载器：parse_skill_md / scan_builtin_skills / load_builtin_skill
- 注册表：SkillRegistry（合并 builtin + custom、索引构建、缓存）
- 默认适配器：MySQLSkillRepository（见 adapters.mysql_repo）

用法示例：

    from skill_core import SkillRegistry, MySQLSkillRepository

    repo = MySQLSkillRepository(session_factory=my_session_factory)
    registry = SkillRegistry(builtin_dir=Path("./skills"), repo=repo)
    index_text = registry.build_index(enabled_tools={"search_knowledge_base", ...})
"""

from skill_core.ports import SkillRepository, ScanResult, scan_content
from skill_core.types import (
    CustomSkillRecord,
    ParsedSkill,
    Skill,
    SkillDescriptor,
)
from skill_core.loader import (
    load_builtin_skill,
    parse_skill_md,
    read_builtin_file,
    scan_builtin_skills,
)
from skill_core.registry import SkillRegistry

__all__ = [
    # 类型
    "SkillDescriptor",
    "Skill",
    "CustomSkillRecord",
    "ParsedSkill",
    # 端口
    "SkillRepository",
    "ScanResult",
    "scan_content",
    # 加载器
    "parse_skill_md",
    "scan_builtin_skills",
    "load_builtin_skill",
    "read_builtin_file",
    # 注册表
    "SkillRegistry",
]
