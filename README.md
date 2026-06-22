# skill_core

Skill 技能系统核心包（runtime/ORM 无关，多后端复用）。

## 架构

```
skill_core/
├── types.py          # 领域类型：SkillDescriptor / Skill / CustomSkillRecord
├── ports.py          # 持久化端口：SkillRepository（Protocol）+ ScanResult
├── loader.py         # 加载器：frontmatter 解析、内置技能扫描、正文/附件读取
├── registry.py       # 注册表：SkillRegistry（合并 builtin+custom、索引构建、缓存）
├── security.py       # 安全扫描：scan_content() 纯函数
└── adapters/
    └── mysql_repo.py # 默认 MySQL 适配：MySQLSkillRepository + DDL
```

## 依赖方向

- 本包**不依赖**任何 agent 框架、不写死 ORM 连接。
- `SkillService`（管理服务）和各后端 Agent 适配都 import 本包。
- `MySQLSkillRepository` 的 session 由调用方注入。
