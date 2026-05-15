# app/

核心代码。各子模块详文见对应 `AGENTS.md`。

| 子目录 | 职责 | 详文 |
|--------|------|------|
| agents/ | 工作流编排、规则引擎、概率推断、提示词 | agents/AGENTS.md |
| voice/ | 语音流水线（录音→VAD→ASR） | — |
| scheduler/ | 主动调度器（后台轮询触发） | — |
| tools/ | 工具调用框架 | — |
| api/ | REST路由、SSE流式、服务生命周期 | api/AGENTS.md |
| memory/ | MemoryBank(FAISS+Ebbinghaus)、隐私保护 | memory/AGENTS.md |
| models/ | LLM多provider fallback、Embedding | models/AGENTS.md |
| schemas/ | 驾驶上下文Pydantic模型、查询Schema | schemas/AGENTS.md |
| storage/ | TOML异步存储、JSONL追加写入 | storage/AGENTS.md |

`config.py` — 应用级配置（数据目录路径等），无独立文档。
