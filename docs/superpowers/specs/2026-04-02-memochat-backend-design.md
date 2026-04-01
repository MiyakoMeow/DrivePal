# MemoChat 独立记忆后端设计

## 概述

将 [MemoChat](https://github.com/LuJunru/MemoChat) 论文的三阶段记忆 pipeline（summarization → retrieval → chatting）集成到知情车秘项目中，作为独立的 `MemoryStore` 后端实现。

**核心差异**：MemoChat 让 LLM 自身管理记忆（写/检索全靠 prompt），而现有 MemoryBank 后端用工程管道（embedding 检索 + 遗忘曲线）。两个后端代表不同的记忆策略，可在 VehicleMemBench 基准中对比评估。

## 决策记录

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 集成方式 | 独立后端（方案 A） | 符合现有 Protocol + Registry 架构 |
| LLM 检索策略 | 枚举可选（默认全量 LLM） | 用户要求 |
| LLM 适配方式 | Prompt Engineering | 不依赖微调模型，用车秘现有 LLM |
| 持久化 | TOMLStore | 复用现有存储体系 |
| 人格分析 | 复用 PersonalityManager | 一致性，避免重复实现 |

## 文件结构

```
app/memory/stores/memochat/
├── __init__.py       # 导出 MemoChatStore
├── store.py          # MemoChatStore（实现 MemoryStore Protocol）
├── engine.py         # MemoChatEngine（核心三阶段 pipeline）
├── prompts.py        # 适配后的 prompt 模板
└── retriever.py      # RetrievalMode 枚举 + 检索策略实现
```

需要修改的现有文件：
- `app/memory/types.py` — 新增 `MEMOCHAT = "memochat"` 枚举值
- `app/memory/memory.py` — `_import_all_stores()` 注册 MemoChatStore

## 核心组件

### 1. MemoChatStore (`store.py`)

实现 `MemoryStore` Protocol，组合以下组件：

- `EventStorage`（复用 `components.py`）→ 事件 CRUD
- `FeedbackManager`（复用 `components.py`）→ 反馈管理
- `PersonalityManager`（复用 `memory_bank/personality.py`）→ 人格分析
- `MemoChatEngine`（新建）→ 核心三阶段 pipeline

类属性：
```python
store_name = "memochat"
requires_embedding = True   # 混合检索模式需要
requires_chat = True        # 三阶段都需要 LLM
supports_interaction = True
```

构造参数：
```python
def __init__(
    self,
    data_dir: Path,
    embedding_model: EmbeddingModel | None = None,
    chat_model: ChatModel | None = None,
    retrieval_mode: RetrievalMode = RetrievalMode.FULL_LLM,
) -> None
```

### 2. MemoChatEngine (`engine.py`)

核心三阶段 pipeline 引擎。

#### 数据结构

**Recent Dialogs**（滑动窗口）：
- 存储于 `memochat_recent_dialogs.toml`（TOMLStore, list）
- 初始化为 `["user: 你好！", "bot: 你好！我是你的行车助手。"]`
- 触发 summarization 后截断到最近 2 条

**Memos**（长期记忆）：
- 存储于 `memochat_memos.toml`（TOMLStore, dict）
- 结构：`{topics: {topic_name: [{summary, dialogs, created_at, memory_strength, last_recall_date}]}}`
- 特殊 key `"NOTO"` 存放无法归类的内容

#### 阈值常量

```python
MAX_LEN = 2048
TARGET_LEN = 512
SUMMARIZATION_WORD_THRESHOLD = MAX_LEN // 2  # 1024 词
SUMMARIZATION_TURN_THRESHOLD = 10
RECENT_DIALOGS_KEEP_AFTER_SUMMARY = 2
```

#### Stage 1: Summarization

方法：`_summarize_if_needed()`

**触发条件**：Recent Dialogs 字数 > `SUMMARIZATION_WORD_THRESHOLD` 或条目数 >= `SUMMARIZATION_TURN_THRESHOLD`

**流程**：
1. 取 Recent Dialogs（去掉前 2 条问候语），编号展示
2. 用 `writing_dialogsum` prompt 让 LLM 提取 `[{"topic", "summary", "start", "end"}]`
3. 按 topic 写入 memos TOML，同时创建 MemoryEvent（topic + summary 作为 content，dialogs 作为 description）写入事件存储
4. 截断 Recent Dialogs 到最近 2 条
5. 若 LLM 未产出任何有效 topic，fallback：随机取样 2 条放入 `NOTO`

#### Stage 2: Retrieval

方法：`_retrieve(query, top_k) -> list[SearchResult]`

**两种模式**（`RetrievalMode` 枚举）：

```python
class RetrievalMode(StrEnum):
    FULL_LLM = "full_llm"
    HYBRID = "hybrid"
```

**FULL_LLM 模式**（默认）：
1. 展平所有 memo 条目为 `(topic, summary, dialogs)` 元组列表
2. 编号展示给 LLM，使用 `retrieval` prompt
3. LLM 输出选择编号（如 `2#5`）
4. 匹配的 memo 转为 `SearchResult`

**HYBRID 模式**：
1. 先用 embedding cosine similarity 粗筛 top-k 候选
2. 仅将候选列表给 LLM 精筛（同样使用 retrieval prompt）
3. 无 embedding 时降级为 keyword 粗筛

**SearchResult 映射**：
```python
SearchResult(
    event={
        "id": memo_entry_id,
        "content": f"{topic}: {summary}",
        "description": " ### ".join(dialogs),
        "source": "memochat_memo",
    },
    score=1.0,  # LLM 选择的记为 1.0
    source="event",
    interactions=[],
)
```

#### Stage 3: Chat

**不在 MemoChatStore 中实现**。chat 响应由上层 AgentWorkflow 调用 ChatModel 完成。MemoChatStore 只负责记忆的写/检索/读。

### 3. Prompt 模板 (`prompts.py`)

参考 MemoChat `data/prompts.json`，适配为中文车舱场景：

**WRITING_PROMPT**（summarization）：
- system：展示编号对话，提取 topic + summary + 范围
- 调整为中文提示词

**RETRIEVAL_PROMPT**：
- system：展示 Query Sentence + Topic Options，选择相关编号
- 保留 `#` 分隔的编号输出格式

### 4. 检索策略 (`retriever.py`)

```python
class RetrievalMode(StrEnum):
    FULL_LLM = "full_llm"
    HYBRID = "hybrid"

async def retrieve_full_llm(
    chat_model: ChatModel,
    query: str,
    memos: dict[str, list[dict]],
    top_k: int,
) -> list[tuple[str, dict]]: ...

async def retrieve_hybrid(
    chat_model: ChatModel,
    embedding_model: EmbeddingModel | None,
    query: str,
    memos: dict[str, list[dict]],
    top_k: int,
) -> list[tuple[str, dict]]: ...
```

## 接口映射

| MemoryStore 方法 | MemoChat 行为 |
|---|---|
| `write(event)` | 直接创建 memo 条目（topic = event.type, summary = event.content），写入 memos TOML + 事件存储 |
| `write_interaction(query, response)` | 追加到 Recent Dialogs → 触发 summarization（若超阈值）→ 触发人格分析 |
| `search(query, top_k)` | 执行 retrieval（按 RetrievalMode）→ 返回匹配的 SearchResult 列表 |
| `get_history(limit)` | 从 memos TOML 读取最近条目，映射为 MemoryEvent 列表 |
| `update_feedback(event_id, feedback)` | 委托 FeedbackManager |

## 数据流

### write_interaction 流程

```
query + response
    ↓
追加到 Recent Dialogs
    ↓
字数/条目超阈值？ ──否──→ 结束
    ↓ 是
Stage 1: Summarization
    ↓
LLM 提取 topic+summary → 写入 memos TOML + 事件存储
    ↓
截断 Recent Dialogs 到 2 条
    ↓
触发 PersonalityManager.maybe_summarize()
```

### search 流程

```
query
    ↓
读取 memos TOML
    ↓
RetrievalMode?
    ├── FULL_LLM: 展平所有 memo → LLM 选择编号 → 返回匹配
    └── HYBRID:   embedding/keyword 粗筛 → LLM 精筛 → 返回匹配
    ↓
映射为 SearchResult 列表
```

## 注册集成

### types.py

```python
class MemoryMode(StrEnum):
    MEMORY_BANK = "memory_bank"
    MEMOCHAT = "memochat"
```

### memory.py

```python
def _import_all_stores() -> None:
    from app.memory.stores.memory_bank import MemoryBankStore
    from app.memory.stores.memochat import MemoChatStore

    register_store(MemoryMode.MEMORY_BANK, MemoryBankStore)
    register_store(MemoryMode.MEMOCHAT, MemoChatStore)
```

## 复用组件清单

| 组件 | 来源文件 | 用途 |
|------|---------|------|
| `EventStorage` | `app/memory/components.py` | 事件 CRUD + ID 生成 |
| `FeedbackManager` | `app/memory/components.py` | 反馈记录 + 策略权重 |
| `forgetting_curve` | `app/memory/components.py` | 遗忘曲线衰减计算 |
| `PersonalityManager` | `app/memory/stores/memory_bank/personality.py` | 人格分析 |
| `TOMLStore` | `app/storage/toml_store.py` | TOML 文件持久化 |
| `cosine_similarity` | `app/memory/utils.py` | embedding 相似度计算 |
| `ChatModel` | `app/models/chat.py` | LLM 调用 |
| `EmbeddingModel` | `app/models/embedding.py` | embedding 编码 |

## 不做的事

- **不引入 MemoChat 的微调模型**：通过 prompt engineering 让现有 LLM 执行三阶段任务
- **不实现 chat 阶段**：chat 由上层 AgentWorkflow 负责
- **不修改 MemoryBank 后端**：两个后端完全独立
- **不引入新依赖**：全部使用现有依赖
