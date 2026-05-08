# MemoryBank 四阶段架构改造

> 状态：待审查 | 日期：2026-05-09

## 背景

经 DrivePal 与 VehicleMemBench 两方 MemoryBank 实现逐项对比，确认算法层高度对齐，工程层存五类差异。本文档涵盖全部四阶段改造。不保证向后兼容。

---

## 阶段一：核心架构改造

### 一、完整多用户隔离

#### 策略：构造时绑定用户，消灭所有 `user_id` 参数

`FaissIndex` 已是单用户单元——构造时收 `data_dir`，内部不感知多用户。当前代码本无 `user_id` 参数。多用户隔离只需在 `MemoryModule` 层加注册表，下层零改动。

#### 架构

```
MemoryModule (facade, +store_registry)
  └─ _stores: dict[str, MemoryBankStore]   # 新增
       └─ get_store(user_id) → MemoryBankStore
            └─ FaissIndex(f"{data_dir}/user_{user_id}/")  # 子目录隔离
            └─ RetrievalPipeline  (不变, 无 user_id)
            └─ MemoryLifecycle    (不变, 无 user_id)
            └─ Summarizer         (不变, 无 user_id)
            └─ ForgettingCurve    (不变, 无 user_id)
            └─ LlmClient          (不变, 无 user_id)
            └─ BackgroundTaskRunner (每 store 独立)
```

#### MemoryModule 薄注册表

```python
class MemoryModule:
    _stores: dict[str, MemoryBankStore] = {}

    def get_store(self, user_id: str = "default") -> MemoryBankStore:
        if user_id not in self._stores:
            self._stores[user_id] = MemoryBankStore(
                user_id=user_id,
                data_dir=self._data_dir / "memorybank",
                embedding_model=self._embedding_model,
                chat_model=self._chat_model,
            )
        return self._stores[user_id]

    async def close(self) -> None:
        for store in self._stores.values():
            await store.close()
        self._stores.clear()
```

#### MemoryStore Protocol：追加 `close()` 方法

```python
class MemoryStore(Protocol):
    async def write(self, event: MemoryEvent) -> str: ...
    async def search(self, query: str, top_k: int = 5) -> list[SearchResult]: ...
    async def get_history(self, limit: int = 10) -> list[MemoryEvent]: ...
    async def get_event_type(self, event_id: str) -> str | None: ...
    async def update_feedback(self, event_id: str, feedback: FeedbackData) -> None: ...
    async def write_interaction(self, query: str, response: str, event_type: str = "reminder", **kwargs: object) -> InteractionResult: ...
    async def close(self) -> None: ...   # 新增——优雅关闭
```

#### FaissIndex 零改动证明

```python
# 旧（当前）—— 单用户，data_dir 写死
self._index = FaissIndex(data_dir, config.embedding_dim)

# 新 —— 每用户独立子目录，其余不变
user_dir = data_dir / f"user_{user_id}"
self._index = FaissIndex(user_dir, config.embedding_dim)
#                                             ↑ 完全相同的构造签名
```

#### 权衡

- **优**：FaissIndex / 检索管道 / 摘要器零改动；测试天然隔离；每用户独立 BackgroundTaskRunner 无并发竞争
- **劣**：用户数增长 → store 实例膨胀。车载场景 ≤6 用户，可接受
- **弃案**：每方法传 `user_id` → 污染 6 个组件 20+ 方法签名，不选

---

### 二、错误处理体系

#### 异常层次

```python
# app/memory/exceptions.py（新增）

class MemoryBankError(Exception):
    """MemoryBank 异常基类。"""

class TransientError(MemoryBankError):
    """可重试的瞬态错误（网络、超时、限速）。"""
    def __init__(self, message: str, retry_after: float = 1.0):
        super().__init__(message)
        self.retry_after = retry_after

class FatalError(MemoryBankError):
    """不可恢复的永久错误（配置、数据损坏）。"""

class LLMCallFailed(TransientError):
    """LLM 调用失败（可重试）。"""

class EmbeddingFailed(TransientError):
    """嵌入 API 调用失败（可重试）。"""

class SummarizationEmpty(MemoryBankError):
    """LLM 返回空结果——非错误，哨兵信号。"""

class ConfigError(FatalError):
    """配置错误（缺失必要参数、值非法）。"""

class MetadataCorrupted(FatalError):
    """元数据损坏，不可自动恢复。"""

class IndexIntegrityError(FatalError):
    """FAISS 索引文件损坏，不可读取。"""
```

#### 各组件改造原则

| 组件 | 当前 | 改为 |
|------|------|------|
| `LlmClient.call()` | 返回 `str \| None`（`None`=失败，`""`=空结果） | 返回 `str`（非空）。抛 `LLMCallFailed`（API 失败）或 `SummarizationEmpty`（空内容哨兵异常） |
| `Summarizer` 四个方法 | 返回 `None`，内部吞异常 | 调用 `LlmClient.call()`。捕获 `SummarizationEmpty` → 返回 `None`（正常）；`LLMCallFailed` → 上抛 |
| `RetrievalPipeline.search()` | embedding 失败透传异常 | **不变**——异常自然上浮，由 `MemoryBankStore.search()` 统一捕获 |
| `MemoryLifecycle.write()` | 内部吞异常 | 写入失败抛 `FatalError`，由调用方（GraphQL）决定 |
| `compute_ingestion_forget_ids` | 静默 `return []` | 记录 warning + 返回 `[]`（降级） |
| `_background_summarize`（lifecycle.py） | `except Exception: logger.warning` | 捕获 `TransientError` → 日志告警；`FatalError` → 上抛 |

#### 降级策略

调用链顶层不抛异常，降级为日志 + 安全默认值：

- `MemoryBankStore.search()`：异常捕获后返回空结果
- `MemoryBankStore.write()`：写入失败抛 `FatalError`（无合理降级）
- 后台任务（summary）：失败由 `BackgroundTaskRunner._on_task_done` 记录，不影响主流程

---

### 三、配置全量集中

#### `MemoryBankConfig` 完整定义

```python
class MemoryBankConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MEMORYBANK_", case_sensitive=False)

    # ── 遗忘 ──
    enable_forgetting: bool = False
    forget_mode: Literal["deterministic", "probabilistic"] = "deterministic"
    soft_forget_threshold: float = 0.3   # 0.15→0.3，见阶段三
    forget_interval_seconds: int = 300
    forgetting_time_scale: float = 1.0   # ← 从 forget.py 模块常量迁入
    seed: int | None = None

    # ── 检索 ──
    chunk_size: int | None = None
    default_chunk_size: int = 1500
    chunk_size_min: int = 200
    chunk_size_max: int = 8192
    coarse_search_factor: int = 4
    embedding_min_similarity: float = 0.3

    # ── LLM（新增）──
    llm_max_retries: int = 3             # ← llm.py LLM_MAX_RETRIES
    llm_trim_start: int = 1800           # ← llm.py LLM_TRIM_START
    llm_trim_step: int = 200             # ← llm.py LLM_TRIM_STEP
    llm_trim_min: int = 500              # ← llm.py LLM_TRIM_MIN
    llm_anchor_user: str = "Hello! Please help me summarize the content of the conversation."
    llm_anchor_assistant: str = "Sure, I will do my best to assist you."
    llm_temperature: float | None = None # None = 使用 ChatModel 默认
    llm_max_tokens: int | None = None

    # ── 摘要 ──
    summary_system_prompt: str = (
        "You are an in-car AI assistant with expertise in remembering "
        "vehicle preferences, driving habits, and in-car conversation context."
    )

    # ── 嵌入 ──
    embedding_dim: int = 1536
    embedding_batch_size: int = 100      # 32→100，对齐 VMB

    # ── 持久化 ──
    save_interval_seconds: float = 30.0  # 新增：search 后持久化节流间隔
    reference_date: str | None = None
    reference_date_auto: bool = False    # 新增：从 metadata 自动推算

    # ── 关闭 ──
    shutdown_timeout_seconds: float = 30.0
```

#### 受影响的旧常量迁移

| 旧位置 | 常量 | 迁移后 |
|--------|------|--------|
| `llm.py` | `LLM_MAX_RETRIES`、`LLM_TRIM_START/STEP/MIN` | `config.llm_max_retries`、`config.llm_trim_start/step/min` |
| `llm.py` | `_ANCHOR_USER/ASSISTANT` | `config.llm_anchor_user/assistant` |
| `forget.py` | `FORGETTING_TIME_SCALE` | `config.forgetting_time_scale` |

#### LlmClient 改造接口

```python
# llm.py LlmClient
async def call(self, prompt: str, *, system_prompt: str) -> str:
    """成功返回非空 str。失败抛 LLMCallFailed 或 SummarizationEmpty。"""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": self._config.llm_anchor_user},
        {"role": "assistant", "content": self._config.llm_anchor_assistant},
        {"role": "user", "content": prompt},
    ]
    for attempt in range(self._config.llm_max_retries):
        cut = max(self._config.llm_trim_start - self._config.llm_trim_step * attempt,
                  self._config.llm_trim_min)
        ...
```

---

### 四、索引损坏恢复降级

#### 三级降级策略

| 损坏类型 | 恢复策略 |
|----------|----------|
| `metadata.json` 格式错（JSON 解析失败） | 从 FAISS 索引重建 metadata 骨架（faiss_id+空 text+`corrupted=True`） |
| `extra_metadata.json` 损坏 | 忽略，空 dict 启动（下次摘要自动重建） |
| Count mismatch（ntotal ≠ len(metadata)） | 以 index 为权威：追加缺失骨架 metadata 条目；多余 entry 标记 `orphaned=True` |
| `index.faiss` 读失败/格式错 | 备份 `.bak`，重建空索引 |

#### 实现

```python
@dataclass
class LoadResult:
    ok: bool
    warnings: list[str]
    recovery_actions: list[str]

class FaissIndex:
    async def load(self) -> LoadResult: ...
```

#### 关键逻辑

1. **metadata 损坏、index 正常**：遍历 `n = index.ntotal`，生成 items `{"faiss_id": i, "text": "", "corrupted": True, "memory_strength": 1, "timestamp": ""}`。FAISS 内积检索仍工作（score 有效），text 为空。`corrupted` 仅 `FaissIndex._metadata` 内部字段，不入 Pydantic 模型。`MemoryBankStore.search()` 构建 `SearchResult` 前过滤掉 corrupted 条目
2. **count mismatch**：以 index 为权威（保向量不丢）。多余 metadata 标记 `orphaned=True`（内部字段，同 corrupted）
3. **index.faiss 不可读**：`shutil.copy(path, path.with_suffix(".faiss.bak"))` → 删除 → 重建空索引

---

## 阶段二：性能优化

### 5. 分块大小缓存

每次 search 都 `sorted(len(m.get("text")))` 对全量 metadata 排序 O(n log n)，大部分时间 n 不变。

```python
class RetrievalPipeline:
    _cached_chunk_size: int | None = None
    _cached_metadata_len: int = 0

    def _get_chunk_size(self, metadata: list[dict], config: MemoryBankConfig) -> int:
        if self._cached_chunk_size is not None and len(metadata) == self._cached_metadata_len:
            return self._cached_chunk_size
        self._cached_chunk_size = _get_effective_chunk_size(metadata, config)
        self._cached_metadata_len = len(metadata)
        return self._cached_chunk_size
```

### 6. 持久化降频

当前每次 `search()` 的 `updated=True` 时全量 `save_index()`（FAISS 写盘 + JSON dump ×3），阻塞 async 事件循环。

```python
class MemoryBankStore:
    _last_save_time: float = 0.0

    async def _maybe_save(self) -> None:
        now = time.monotonic()
        if now - self._last_save_time >= self._config.save_interval_seconds:
            await self._index.save()
            self._last_save_time = now

    async def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        ...
        if updated:
            await self._maybe_save()  # 不再每次写盘
        ...
```

`close()` 中强制 `save()`。损失 ≤30s memory_strength 持久化——遗忘以天计，可接受。

### 7. 嵌入批量编码

当前 `lifecycle.write()` 逐对编码（N 对 = N 次 API 调用）。改为先收集全部 pair_texts，一次 `encode_batch()`。

```python
async def write(self, event: MemoryEvent) -> str:
    ...
    pair_texts: list[str] = []
    pair_metas: list[dict] = []

    for i in range(0, len(parsed_pairs), 2):
        pair_texts.append(conv_text)
        pair_metas.append({"speakers": [...], "source": date_key, ...})

    embeddings = await self._embedding_client.encode_batch(pair_texts)
    for emb, meta in zip(embeddings, pair_metas, strict=True):
        fid = await self._index.add_vector(text, emb, ts, meta)
```

`EmbeddingClient.encode_batch()` 已存在（纯代理层），无需改。

---

## 阶段三：功能增强

### 8. 遗忘阈值调参

soft_forget_threshold: 0.15 → 0.3。原因：0.15 下 strength=1 的条目 ~2 天即遗忘，在线服务场景过于激进。

实际遗忘窗口对比：

| memory_strength | 0.15 阈值 → 天数 | 0.3 阈值 → 天数 |
|----------------|-----------------|----------------|
| 1（新记忆） | ~1.9 天 | ~1.2 天 |
| 3（命中 2 次） | ~5.7 天 | ~3.6 天 |
| 5（命中 4 次） | ~9.5 天 | ~6 天 |
| 10（频繁命中） | ~19 天 | ~12 天 |

公式、节流、双模式均不变。仅常量改。

### 9. reference_date 自动计算

```python
class FaissIndex:
    def compute_reference_date(self, offset_days: int = 1) -> str:
        """扫描 metadata 找最大 timestamp，返回 +offset_days 的日期。"""
        if not self._metadata:
            return datetime.now(UTC).strftime("%Y-%m-%d")
        max_ts = max(
            (m.get("timestamp", "")[:10] for m in self._metadata), default=""
        )
        if not max_ts:
            return datetime.now(UTC).strftime("%Y-%m-%d")
        ref = date.fromisoformat(max_ts) + timedelta(days=offset_days)
        return ref.strftime("%Y-%m-%d")
```

遗忘计算优先级：`config.reference_date` > `index.compute_reference_date()`（若 auto） > `datetime.now(UTC)`

### 10. LLM 调用参数显式控制

```python
class LlmClient:
    async def call(self, prompt: str, *, system_prompt: str, **kwargs: object) -> str:
        ...
        resp = await self._chat_model.generate(
            messages=messages,
            temperature=kwargs.get("temperature", self._config.llm_temperature),
            max_tokens=kwargs.get("max_tokens", self._config.llm_max_tokens),
        )
```

`Summarizer` 调用时显式传入低温：

```python
result = await self._llm.call(
    prompt,
    system_prompt=config.summary_system_prompt,
    temperature=0.3,
    max_tokens=400,
)
```

### 11. 嵌入批次大小对齐 VMB

`config.embedding_batch_size`: 32 → 100。

### 12. 格式化输出（移植 VMB `format_search_results`）

新增方法，不改变 `search()` 返回值（保持 GraphQL schema 不变）。

```python
# store.py
async def format_search_results(self, query: str, top_k: int = 5) -> str:
    """返回 human-readable 检索结果文本（LLM prompt 注入用）。
    按 source 分组 + memory_strength + 日期标注。
    """
    results = await self.search(query, top_k)
    # 按 source 分组聚合，输出 "[memory_strength=N] [date=YYYY-MM-DD] text"
    ...
    return formatted_text
```

调用场景：Agent 工作流中 Strategy/Execution Agent 将记忆检索结果注入 system prompt。

---

## 阶段四：质量保障

### 13. 关键路径测试覆盖

| 测试文件（新增） | 覆盖内容 |
|----------|----------|
| `tests/test_retrieval_pipeline.py` | 四阶段管道：mock FaissIndex + mock EmbeddingClient，验证各阶段产出 |
| `tests/test_forgetting.py` | `ForgettingCurve.maybe_forget()` 节流与标记；`compute_ingestion_forget_ids()` 概率/确定模式 |
| `tests/test_summarizer.py` | 不可变保护：两次调用 verify 第二次跳过 |
| `tests/test_multi_user.py` | 两用户隔离：各写数据，verify 互相不可见 |
| `tests/test_index_recovery.py` | 损坏降级：空 JSON/格式错/count mismatch → verify LoadResult |

扩展现有：

| 测试文件（改） | 覆盖内容 |
|----------|----------|
| `tests/test_memory_bank.py` | 说话人过滤（正分/负分 ×0.75/×1.25）、合并去重（并查集重叠场景） |

### 14. 可观测性

```python
# app/memory/memory_bank/observability.py（新增）

@dataclass
class MemoryBankMetrics:
    search_count: int = 0
    search_empty_count: int = 0
    search_latency_ms: list[float] = field(default_factory=list)   # 环形缓冲 100
    embedding_latency_ms: list[float] = field(default_factory=list)
    forget_count: int = 0
    forget_removed_count: int = 0
    background_task_failures: int = 0
    index_load_warnings: list[str] = field(default_factory=list)
    store_instance_count: int = 0

    def snapshot(self) -> dict: ...
    def reset(self) -> None: ...
```

#### 埋点位置

| 埋点位置 | 指标 |
|----------|------|
| `RetrievalPipeline.search()` 入口/出口 | search_count, search_latency_ms, search_empty_count |
| `EmbeddingClient.encode_batch()` | embedding_latency_ms |
| `ForgettingCurve.maybe_forget()` | forget_count, forget_removed_count |
| `_background_summarize` 异常捕获 | background_task_failures |
| `FaissIndex.load()` 降级恢复 | index_load_warnings |
| `MemoryModule.get_store()` | store_instance_count |

暴露方式：`MemoryBankStore.metrics` → `MemoryModule.get_metrics(user_id)` → GraphQL 按需查询字段。

---

## 影响文件总表

| 文件 | 涉及阶段 | 操作 |
|------|----------|------|
| `app/memory/exceptions.py` | 一 | **新增** |
| `app/memory/memory_bank/observability.py` | 四 | **新增** |
| `app/memory/memory_bank/config.py` | 一、二、三 | 改：字段扩充、阈值调整 |
| `app/memory/memory_bank/llm.py` | 一、三 | 改：异常体系、配置调用、**kwargs |
| `app/memory/memory_bank/index.py` | 一、三、四 | 改：LoadResult、compute_reference_date、埋点 |
| `app/memory/memory_bank/store.py` | 一、二、三、四 | 改：user_id 构造、持久化降频、format_search_results、metrics |
| `app/memory/memory_bank/lifecycle.py` | 一、二、三、四 | 改：异常体系、嵌入批量、埋点 |
| `app/memory/memory_bank/summarizer.py` | 一、三 | 改：异常体系、LLM 参数 |
| `app/memory/memory_bank/forget.py` | 一、三、四 | 改：配置调用、reference_date_auto、埋点 |
| `app/memory/memory_bank/retrieval.py` | 二、四 | 改：分块缓存、埋点 |
| `app/memory/memory.py` | 一 | 改：store 注册表 |
| `app/memory/interfaces.py` | 一 | 改：追加 close() |
| `tests/test_retrieval_pipeline.py` | 四 | **新增** |
| `tests/test_forgetting.py` | 四 | **新增** |
| `tests/test_summarizer.py` | 四 | **新增** |
| `tests/test_multi_user.py` | 四 | **新增** |
| `tests/test_index_recovery.py` | 四 | **新增** |
| `tests/test_memory_bank.py` | 四 | 改：扩展场景 |
| `app/memory/memory_bank/bg_tasks.py` | 无 | 不变 |
| `app/memory/memory_bank/index_reader.py` | 无 | 不变 |
| `app/memory/schemas.py` | 无 | 不变 |
| `app/memory/embedding_client.py` | 无 | 不变 |

## 未解决问题

1. 内存中同时持有多个 store 实例（每用户一个），车载场景 ≤6 用户，每实例开销 ~10MB（FAISS 索引），总量可控。若未来需大量用户，需 LRU 淘汰策略
2. `format_search_results` 的具体格式细节留实现阶段确定（分组键、编号规则、日期格式）
3. 测试 mock 策略：`EmbeddingModel`/`ChatModel` 已有接口，需确认 mock 粒度（方法级 vs 类级）
