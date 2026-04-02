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
| embedding 依赖 | `requires_embedding = False` | FULL_LLM 模式不需要 embedding；HYBRID 模式内部处理 Optional |

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
- `app/memory/memory.py` — `_import_all_stores()` 注册 MemoChatStore；`_create_store()` 支持 `**kwargs` 透传

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
requires_embedding = False  # FULL_LLM 不需要；HYBRID 内部处理 Optional
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
- 存储于 `memochat_recent_dialogs.toml`（TOMLStore, list, default_factory=list）
- 引擎初始化时检查：若为空列表，填充默认问候 `["user: 你好！", "bot: 你好！我是你的行车助手。"]`
- 触发 summarization 后截断到最近 2 条

**Memos**（长期记忆）：
- 存储于 `memochat_memos.toml`（TOMLStore, dict, default_factory 返回 `{}`)
- 结构：`{topic_name: [{id, summary, dialogs, created_at, memory_strength, last_recall_date}]}`
- 每个 memo 条目包含 `id` 字段（格式：`EventStorage.generate_id()`），用于 feedback 和 history 定位
- 特殊 key `"NOTO"` 存放无法归类的内容
- 注意：topic_name 直接作为顶层 key，无中间 `topics` 层

**Interactions**（交互记录）：
- 存储于 `memochat_interactions.toml`（TOMLStore, list, default_factory=list）
- 每条记录包含 `{id, event_id, query, response, timestamp}`
- 用于 PersonalityManager 的 `maybe_summarize()` 调用

#### 并发控制

使用 `asyncio.Lock()` 保护涉及多 TOML 文件读写的操作（summarization 中 dialogs + memos + events + interactions 的写入）。

#### 阈值常量

```python
MAX_LEN = 2048
TARGET_LEN = 512
SUMMARIZATION_CHAR_THRESHOLD = MAX_LEN // 2  # 1024 字符（len(text)）
SUMMARIZATION_TURN_THRESHOLD = 10
RECENT_DIALOGS_KEEP_AFTER_SUMMARY = 2
```

"字数"定义为 `len(text)`（字符数），对中英文统一处理。

#### Stage 1: Summarization

方法：`_summarize_if_needed()`

**触发条件**：`len("".join(recent_dialogs))` > `SUMMARIZATION_CHAR_THRESHOLD` 或条目数 >= `SUMMARIZATION_TURN_THRESHOLD`

**流程**：
1. 取 Recent Dialogs（去掉前 2 条问候语），编号展示
2. 用 `writing_dialogsum` prompt 让 LLM 提取 `[{"topic", "summary", "start", "end"}]`
3. 按 topic 写入 memos TOML（带 id），同时创建 MemoryEvent（topic + summary 作为 content，dialogs 作为 description）写入事件存储
4. 截断 Recent Dialogs 到最近 2 条
5. 若 LLM 未产出任何有效 topic，fallback：随机取样 2 条放入 `NOTO`

**LLM 错误处理**：
- JSON 解析失败：尝试 `re.findall` 提取结构化数据（参考 MemoChat `normalize_model_outputs`）
- 完全无法解析：走 fallback 路径（随机取样放入 NOTO）
- LLM 调用异常（网络超时等）：log warning，跳过 summarization，不截断 Recent Dialogs

#### Stage 2: Retrieval

方法：`_retrieve(query, top_k) -> list[SearchResult]`

**两种模式**（`RetrievalMode` 枚举）：

```python
class RetrievalMode(StrEnum):
    FULL_LLM = "full_llm"
    HYBRID = "hybrid"
```

**FULL_LLM 模式**（默认）：
1. 展平所有 memo 条目为 `(topic, entry)` 元组列表
2. 编号展示给 LLM，使用 `retrieval` prompt
3. LLM 输出选择编号（如 `2#5`）
4. 匹配的 memo 转为 `SearchResult`

**HYBRID 模式**：
1. 先用 embedding cosine similarity 粗筛 top-k 候选
2. 仅将候选列表给 LLM 精筛（同样使用 retrieval prompt）
3. 无 embedding 时降级为 keyword 粗筛

**LLM 错误处理**：
- 编号解析失败：跳过无效编号，保留有效编号的匹配
- 全部编号无效：返回空列表
- LLM 调用异常：HYBRID 模式降级为纯 embedding/keyword 结果（无 LLM 精筛）

**SearchResult 映射**：
```python
SearchResult(
    event={
        "id": entry["id"],
        "content": f"{topic}: {entry['summary']}",
        "description": " ### ".join(entry["dialogs"]),
    },
    score=1.0,
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

`memos` 参数结构为 `{topic_name: [{id, summary, dialogs, ...}]}`，topic_name 直接作为 key。

## 接口映射

| MemoryStore 方法 | MemoChat 行为 |
|---|---|
| `write(event)` | 直接创建 memo 条目（topic = event.type, summary = event.content, id 由 EventStorage 生成），写入 memos TOML + 事件存储 |
| `write_interaction(query, response)` | 追加到 Recent Dialogs + interactions TOML → 触发 summarization（若超阈值）→ 触发 PersonalityManager.maybe_summarize() |
| `search(query, top_k)` | 执行 retrieval（按 RetrievalMode）→ 返回匹配的 SearchResult 列表 |
| `get_history(limit)` | 从 memos TOML 读取，按 created_at 排序取最近 limit 条，映射为 MemoryEvent |
| `update_feedback(event_id, feedback)` | 委托 FeedbackManager |

### get_history() 字段映射

| MemoryEvent 字段 | memo 条目来源 |
|---|---|
| `id` | `entry["id"]` |
| `content` | `f"{topic}: {entry['summary']}"` |
| `type` | `"memochat_memo"` |
| `description` | `" ### ".join(entry["dialogs"])` |
| `memory_strength` | `entry.get("memory_strength", 1)` |
| `last_recall_date` | `entry.get("last_recall_date", "")` |
| `date_group` | `entry.get("created_at", "")[:10]` |
| `created_at` | `entry.get("created_at", "")` |

### write_interaction 与 PersonalityManager 的衔接

`PersonalityManager.maybe_summarize()` 需要 `interactions: list[dict]` 且每条包含 `event_id`。MemoChatEngine 维护独立的 `memochat_interactions.toml`，在 summarization 产生新 memo 时，将对应的 interaction 记录关联到 memo 的 id（作为 `event_id`），确保 PersonalityManager 能正确过滤和计数交互。

## 数据流

### write_interaction 流程

```
query + response
    ↓
追加到 Recent Dialogs
追加到 interactions TOML（关联 summarization 后的 event_id）
    ↓
字符数/条目超阈值？ ──否──→ 触发 PersonalityManager.maybe_summarize() → 结束
    ↓ 是
Stage 1: Summarization
    ↓
LLM 提取 topic+summary → 写入 memos TOML（带 id）+ 事件存储
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

## 工厂集成

### types.py

```python
class MemoryMode(StrEnum):
    MEMORY_BANK = "memory_bank"
    MEMOCHAT = "memochat"
```

### memory.py

`_import_all_stores()` 注册：

```python
def _import_all_stores() -> None:
    from app.memory.stores.memory_bank import MemoryBankStore
    from app.memory.stores.memochat import MemoChatStore

    register_store(MemoryMode.MEMORY_BANK, MemoryBankStore)
    register_store(MemoryMode.MEMOCHAT, MemoChatStore)
```

`_create_store()` 修改：将未识别的 `**kwargs` 透传给 store 构造器，支持 `retrieval_mode` 等扩展参数：

```python
def _create_store(self, mode: MemoryMode) -> MemoryStore:
    ...
    kwargs: dict[str, Any] = {"data_dir": self._data_dir}
    # 现有 embedding/chat 注入逻辑不变
    return store_cls(**kwargs)
```

`retrieval_mode` 的传入方式：通过配置文件或环境变量 `MEMOCHAT_RETRIEVAL_MODE` 读取，在 `_create_store` 中注入到 kwargs。

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
