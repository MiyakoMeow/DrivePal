# App 核心模块

`app/` 目录包含系统核心代码。各子模块的详细文档见对应目录的 `AGENTS.md`。

## 模块职责

- **agents/** — Agent 核心模块：工作流编排、规则引擎、概率推断、提示词模板 → [AGENTS.md](agents/AGENTS.md)
- **api/** — REST API：路由定义、请求/响应模型、SSE 流式 → [AGENTS.md](api/AGENTS.md)
- **memory/** — MemoryBank 记忆系统：FAISS 索引、遗忘曲线、分层摘要、隐私保护 → [AGENTS.md](memory/AGENTS.md)
- **models/** — AI 模型封装：LLM 多 provider fallback、Embedding 调用 → [AGENTS.md](models/AGENTS.md)
- **schemas/** — 数据模型：驾驶上下文 Pydantic 模型 → [AGENTS.md](schemas/AGENTS.md)
- **storage/** — 持久化引擎：TOML 异步存储、JSONL 追加写入 → [AGENTS.md](storage/AGENTS.md)

`app/config.py` 为应用级配置（数据目录路径等），无独立 AGENTS.md。
