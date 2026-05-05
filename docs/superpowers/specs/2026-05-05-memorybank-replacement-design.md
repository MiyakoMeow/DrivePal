# MemoryBank 替换设计：VehicleMemBench 版移植

## 动机

现有 MemoryBank 实现（`engine.py` 847 行）为独立开发，与原始论文实现有偏差。
VehicleMemBench 的 MemoryBank 组（`memorybank.py` 2050 行）修复了原版 20+ bug，
引入 FAISS 索引和四阶段检索管道。替换而非增量修补，避免维护两套相似实现。

## 范围

完全替换 `app/memory/stores/memory_bank/` 下除 `__init__.py` 外的所有文件，
以及 `app/memory/components.py` 中 MemoryBank 专用组件。保持上层 `MemoryModule`
Facade、`MemoryStore` Protocol、API 层不受影响。

## 文件布局

```
app/memory/stores/memory_bank/
├── __init__.py       ← 更新导出，结构不变
├── store.py          ← MemoryStore Protocol 薄适配器
├── faiss_index.py    ← FAISS 索引 CRUD + 持久化
├── retrieval.py      ← 四阶段检索管道
├── llm.py            ← 异步 LLM 调用封装
├── summarizer.py     ← 摘要与人格生成
└── forget.py         ← 遗忘曲线 + 搜索时触发

app/memory/components.py  ← 删 EventStorage/SimpleInteractionWriter，保留 FeedbackManager/KeywordSearch

# 删除
app/memory/stores/memory_bank/engine.py
app/memory/stores/memory_bank/summarization.py
app/memory/stores/memory_bank/personality.py
```

## 模块职责

### faiss_index.py — FAISS 索引管理

```python
class FaissIndex:
    """FAISS IndexFlatIP 索引 + metadata.json + extra_metadata.json 三文件存储。"""

    def __init__(self, data_dir: Path, embedding_dim: int = 1536)
    async def load(self) -> None                       # 加载或新建；损坏自动重建（单用户）
    async def save(self) -> None                       # 持久化三文件
    async def add_vector(self, text, embedding, timestamp, extra_meta) -> int  # 返回 faiss_id
    async def remove_vectors(self, faiss_ids: list[int])
    async def search(self, query_emb, top_k) -> list[dict]  # 原始 FAISS 调用
    async def update_metadata(self, faiss_id, updates)
    async def get_metadata(self) -> list[dict]
    @property
    def total(self) -> int                             # 索引条目数
```

设计决策：
- 单用户：存储直接在 data_dir 下，不以 user_id 分目录
- Embedding 由外部传入，本模块不调用 API
- `add_vector` 内部做 L2 归一化（IndexFlatIP 需要）

### retrieval.py — 四阶段检索管道

```python
class RetrievalPipeline:
    """粗排→邻居合并→重叠去重→说话人过滤。"""

    def __init__(self, index: FaissIndex, embedding_model: EmbeddingModel)
    async def search(self, query: str, top_k: int = 5) -> list[ResultItem]
```

ResultItem: `{text, score, source, memory_strength, speakers, timestamp, _meta_idx}`

| 阶段 | 操作 |
|------|------|
| ① 粗排 | query_emb + L2 归一化 → FAISS search(`top_k × 4`) |
| ② 邻居合并 | 同 `source` 连续条目合并，deque 双向裁剪至 chunk_size |
| ③ 重叠去重 | 并查集跨结果索引重叠消除 |
| ④ 说话人过滤 | query 提及已知用户 → 不涉及该用户的记忆 score × 0.75 |

说话人过滤在本项目单用户场景作用有限但仍保留，零额外成本。

### llm.py — LLM 调用封装

```python
class LlmClient:
    """ChatModel 薄封装：重试 + 上下文长度截断。"""

    def __init__(self, chat_model: ChatModel)
    async def call(self, prompt, *, system_prompt=None,
                   max_tokens=400, temperature=0.7) -> str | None
```

- 使用项目现有 `ChatModel`（async，多 provider fallback）
- 保留 VMB 的上下文截断重试（`LLM_CTX_TRIM_*`）
- 预计 ~80 行

### summarizer.py — 摘要与人格生成

```python
class Summarizer:
    """按日期生成每日摘要/每日人格/总体摘要/总体人格，不可变保护。"""

    def __init__(self, llm: LlmClient, index: FaissIndex)
    async def ensure_daily_summary(self, date_key: str) -> None
    async def ensure_overall_summary(self) -> None
    async def ensure_daily_personality(self, date_key: str) -> None
    async def ensure_overall_personality(self) -> None
```

- 不可变：一旦生成不覆盖（哨兵值 `GENERATION_EMPTY` 防止重复空调用）
- 每日摘要存为 FAISS 向量（`type=daily_summary`），豁免遗忘
- 总体摘要和人格存入 `extra_metadata.json`，检索时注入首条结果

### forget.py — 遗忘曲线

```python
class ForgettingCurve:
    """艾宾浩斯遗忘曲线 R = e^{-t/S}，搜索时触发。"""

    FORGETTING_TIME_SCALE = 1
    SOFT_FORGET_THRESHOLD = 0.15
    FORGET_INTERVAL_SECONDS = 300

    async def maybe_forget(self, index: FaissIndex,
                           reference_date: str | None = None) -> None
```

- 当前时间作为 reference_date（非 VMB 的基于历史文件推断）
- 确定性软标记：`memory_strength` 计算 retention < 阈值则设 `forgotten = True`
- 不删除向量（保持索引稳定，避免 `remove_ids` 后的 ID 间隙问题）
- 300 秒节流避免高频触发

### store.py — MemoryStore 适配器

```python
class MemoryBankStore:
    """MemoryStore Protocol 实现，组合下层模块。"""

    store_name = "memory_bank"
    requires_embedding = True
    requires_chat = True
    supports_interaction = True

    def __init__(self, data_dir, embedding_model=None, chat_model=None)
    async def write_interaction(self, query, response, event_type="reminder") -> InteractionResult
    async def search(self, query, top_k=10) -> list[SearchResult]
    async def write(self, event: MemoryEvent) -> str
    async def get_history(self, limit=10) -> list[MemoryEvent]
    async def update_feedback(self, event_id, feedback) -> None
    async def get_event_type(self, event_id) -> str | None
```

`write_interaction` 数据流：
```
query + response → pair_text (格式 "[|User|]: {query}; [|AI|]: {response}")
    → embedding.encode(pair_text) → index.add_vector(text, emb, ts, extra_meta)
    → forget.maybe_forget(index)         # await（纯内存计算，快速）
    → asyncio.create_task(summarizer.ensure_*(...))  # fire-and-forget（LLM 调用不阻塞写入）
    → return InteractionResult(event_id=str(faiss_id))
```

格式拼接在 `store.py` 的 `write_interaction` 中完成。`summarizer.ensure_*` 使用
`asyncio.create_task` 异步触发，不阻塞写入路径。`forget.maybe_forget()` 为纯内存
数学计算，直接 await。`write()` 副作用语义与 `write_interaction` 一致。

`search` 数据流：
```
maybe_forget(index) → retrieval.search(query, top_k+1)
    → inject overall_summary/personality as first result
    → strengthen memory_strength of hits
    → index.save()
    → map to list[SearchResult]
```

## 数据模型映射

| 旧模型 | 新模型 |
|--------|--------|
| `MemoryEvent` (id, content, type, strength, interaction_ids) | metadata dict (text, source, speakers, strength, faiss_id, timestamp, type) |
| `InteractionRecord` (query, response, event_id) | message pair 嵌入 text 字段，含 `[|User|]/[|AI|]` 格式 |
| `SearchResult.event` dict | metadata dict (text, score, source, strength) |
| `SearchResult.interactions` | 不再展开（由 faiss_id 关联） |

`MemoryEvent` schema 保留，`write()` 将其 `content` + `description` 转为 FAISS entry。
`write()` 副作用与 `write_interaction` 一致：写入后 await `forget.maybe_forget()`，
`asyncio.create_task(summarizer.ensure_*)` 异步触发。

## 错误处理

| 场景 | 处理 |
|---|---|
| FAISS 索引/JSON 损坏 | `load()` 重建空索引，日志警告 |
| Embedding API 临时故障 | 复用 `EmbeddingModel` retry+backoff |
| LLM 调用失败 | 静默跳过该日，下次写入重试 |
| 元数据字段缺失 | 防御 `get()` + 日志，单条跳过 |
| 存储目录问题 | `OSError` 向上抛 |

## 测试

| 文件 | 内容 |
|------|------|
| `tests/stores/test_faiss_index.py` | CRUD、持久化、损坏重建 |
| `tests/stores/test_retrieval.py` | 四阶段管道各阶段 + mock embedding |
| `tests/stores/test_forget.py` | 遗忘曲线、节流、软标记 |
| `tests/stores/test_summarizer.py` | 摘要触发条件、不可变保护 |
| `tests/stores/test_memory_bank_store.py` | MemoryStore 契约（重写） |
| `tests/test_memory_module_facade.py` | 不变 |
| `tests/test_memory_store_contract.py` | 不变 |

标记 `--test-llm` / `--test-embedding` 控制 LLM/Embedding 依赖测试。

## 配置

全部参数代码硬编码默认值，环境变量覆盖。与 VMB 原设计一致：

| 参数 | 默认值 | 环境变量 |
|------|--------|----------|
| `embedding_dim` | 1536（首次 API 调用后自动校正） | 无（自动检测） |
| `chunk_size` | 1500（自适应校准，下限 200，上限 8192） | `MEMORYBANK_CHUNK_SIZE` |
| `enable_summary` | true | `MEMORYBANK_ENABLE_SUMMARY` |
| `enable_forgetting` | false | `MEMORYBANK_ENABLE_FORGETTING` |
| `forgetting_threshold` | 0.15 | 无 |
| `forget_interval_seconds` | 300 | 无 |

不引入独立配置文件。`config/llm.toml` 维持模型凭证配置定位。

## 已解决问题

以下为头脑风暴阶段分析的三个问题及其结论：

1. **`write_batch()`** — 删除。仅测试代码调用，无生产路径使用。`app/` 目录下 grep 零匹配。若未来需要，调用方逐条调 `write_interaction`。

2. **`reset_forgetting_state()`** — 删除。仅测试代码调用，无生产路径使用。新 `ForgettingCurve` 使用确定性软标记，不需要"重置遗忘状态"概念。

3. **配置加载** — 代码硬编码默认值 + 环境变量覆盖，不引入独立配置文件。理由：6 个 behavioral 参数不值得新 loader（YAGNI）。VMB 原设计已有此模式（`MEMORYBANK_CHUNK_SIZE`、`MEMORYBANK_ENABLE_FORGETTING` 等）。`config/llm.toml` 定位为模型凭证配置，不混合 behavioral params。
