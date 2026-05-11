# App 核心模块

`app/` 目录包含系统核心代码。各子模块的详细文档见对应目录的 `AGENTS.md`。

## 模块索引

| 模块 | 路径 | 文档 |
|------|------|------|
| Agent 系统 | `app/agents/` | [AGENTS.md](agents/AGENTS.md) |
| API 层 | `app/api/` | [AGENTS.md](api/AGENTS.md) |
| 记忆系统 | `app/memory/` | [AGENTS.md](memory/AGENTS.md) |
| 模型封装 | `app/models/` | [AGENTS.md](models/AGENTS.md) |
| 模式定义 | `app/schemas/` | [AGENTS.md](schemas/AGENTS.md) |
| 数据存储 | `app/storage/` | [AGENTS.md](storage/AGENTS.md) |

## 模块职责

- **agents/** — Agent 核心模块：工作流编排、规则引擎、概率推断、提示词模板
- **api/** — GraphQL API：Strawberry 类型定义、Resolver、输入输出转换
- **memory/** — MemoryBank 记忆系统：FAISS 索引、遗忘曲线、分层摘要、隐私保护
- **models/** — AI 模型封装：LLM 多 provider fallback、Embedding 调用
- **schemas/** — 数据模型：驾驶上下文 Pydantic 模型
- **storage/** — 持久化引擎：TOML 异步存储、JSONL 追加写入

`app/config.py` 为应用级配置（阈值常量、数据目录路径等），无独立 AGENTS.md。
