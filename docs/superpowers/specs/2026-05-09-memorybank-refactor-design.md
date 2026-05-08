# MemoryBank 重构设计

## 背景

完成 DrivePal 与 VehicleMemBench 两项目 MemoryBank 实现的完整对比分析。确认核心算法（FAISS 索引、遗忘曲线、四阶段检索、邻居合并、去重、说话人过滤、摘要生成）已对齐，但存在以下问题：

1. 无 inflight 防护，后台摘要可能重复生成
2. 后台任务无关闭清理逻辑
3. `os.getenv` 散落 4+ 文件，无单一配置源
4. `Summarizer` 依赖完整 `FaissIndex`，接口过宽
5. `RetrievalPipeline` 同时接收 `FaissIndex` + `EmbeddingClient`，边界模糊
6. `MemoryBankStore` 集编排、存储、检索于一身，职责过重
7. AGENTS.md 记载 6 项功能代码中不存在

## 目标

- 消除已知 bug（inflight 缺失、关闭清理缺失）
- 集中配置管理（pydantic-settings 替代散落 `os.getenv`）
- 重划模块边界，降低耦合
- AGENTS.md 与代码同步

## 非目标

- 不新增功能特性（如 retention 加权评分、名称匹配加分）
- 不改变外部接口（`MemoryStore` Protocol 不变）
- 不引入多用户隔离（当前单驾驶员场景）

---

## 新模块结构

```
app/memory/memory_bank/
├── __init__.py           # 导出 MemoryBankStore
├── config.py             # [新增] 集中配置模型
├── index.py              # [重命名] 原 faiss_index.py → FaissIndex
├── index_reader.py       # [新增] IndexReader Protocol（只读视图）
├── retrieval.py          # [保持] RetrievalPipeline → 依赖 IndexReader
├── forget.py             # [保持] ForgettingCurve + 辅助函数
├── summarizer.py         # [重构] Summarizer → 依赖 IndexReader
├── llm.py                # [保持] LlmClient
├── lifecycle.py          # [新增] MemoryLifecycle（写入/遗忘/摘要编排）
├── store.py              # [瘦身] MemoryBankStore → Facade
└── bg_tasks.py           # [新增] BackgroundTaskRunner
```

## 组件设计

### config.py — MemoryBankConfig

使用 `pydantic-settings.BaseSettings`，环境变量前缀 `MEMORYBANK_`。

```python
class MemoryBankConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MEMORYBANK_", case_sensitive=False)

    enable_forgetting: bool = False
    forget_mode: str = "deterministic"       # "deterministic" | "probabilistic"
    soft_forget_threshold: float = 0.15
    forget_interval_seconds: int = 300
    forgetting_time_scale: float = 1.0
    seed: int | None = None

    chunk_size: int | None = None            # None → 自适应 P90×3
    chunk_size_min: int = 200
    chunk_size_max: int = 8192
    coarse_search_factor: int = 4
    embedding_min_similarity: float = 0.3

    enable_summary: bool = True
    summary_system_prompt: str = (
        "You are an in-car AI assistant with expertise in remembering "
        "vehicle preferences, driving habits, and in-car conversation context."
    )

    embedding_dim: int = 1536          # 首次 add_vector 后由实际 embedding 维度覆盖；BGE-M3 为 1024
    shutdown_timeout_seconds: float = 30.0
```

各模块通过构造函数接收 `MemoryBankConfig` 实例（依赖注入），不再自行 `os.getenv`。

### index_reader.py — IndexReader Protocol

```python
@runtime_checkable
class IndexReader(Protocol):
    """FaissIndex 只读视图。消费端（Summarizer / RetrievalPipeline）仅依赖此接口。

    get_metadata() 返回的每个 dict 至少含以下键：
      text, source, type, speakers, forgotten, memory_strength, last_recall_date, faiss_id, timestamp
    """

    @property
    def total(self) -> int: ...
    def get_metadata(self) -> list[dict]: ...
    async def search(self, query_emb: list[float], top_k: int) -> list[dict]: ...
    def get_extra(self) -> dict: ...
```

`FaissIndex` 隐式满足此 Protocol，无需适配器。`get_all_speakers()` 不在 Protocol 中（无消费端使用），但保留在 `FaissIndex` 上供未来使用。

### index.py — FaissIndex（重命名自 faiss_index.py）

内容不变。文件重命名以匹配类名惯例。`get_all_speakers()` 保留（维护说话人缓存，虽当前无调用方）。

### retrieval.py — RetrievalPipeline

依赖从 `FaissIndex` 改为 `IndexReader`。`_get_effective_chunk_size` 从 `config.chunk_size` 取值，不再 `os.getenv`。

`_apply_speaker_filter` 通过遍历结果条目中的 `speakers` 字段检测查询提及的说话人，无需访问索引的全局说话人列表。

### summarizer.py — Summarizer

依赖改为 `IndexReader` + `LlmClient` + `config`（获取 `summary_system_prompt`）。

### forget.py — ForgettingCurve

构造函数改为接收 `config: MemoryBankConfig`，`_resolve_forget_mode()` 移除（由 config 统一管理）。`compute_ingestion_forget_ids` 改为接收 `config` 参数。

### bg_tasks.py — BackgroundTaskRunner

```python
class BackgroundTaskRunner:
    def __init__(self, config: MemoryBankConfig): ...
    def spawn(self, coro: Coroutine) -> asyncio.Task: ...
    async def shutdown(self) -> None: ...  # 超时取自 config.shutdown_timeout_seconds
```

- `spawn()` — 创建 `asyncio.Task`，存入内部集合，添加 `done_callback`；失败时日志告警
- `shutdown()` — 取消所有未完成任务，`asyncio.gather(return_exceptions=True)` 等待完成，超时取自 `config.shutdown_timeout_seconds`
- 替换当前全局 `_background_tasks` + `_finalize_task` 的 ad-hoc 管理

### lifecycle.py — MemoryLifecycle

从 `store.py` 拆出，构造函数：

```python
class MemoryLifecycle:
    def __init__(
        self,
        index: FaissIndex,
        embedding_client: EmbeddingClient,
        forget: ForgettingCurve,
        summarizer: Summarizer | None,
        config: MemoryBankConfig,
        bg: BackgroundTaskRunner,
    ) -> None: ...
```

公共方法：

- `write(event: MemoryEvent) -> str` — 多说话人解析 → 向量化 → 存入 FAISS → 遗忘 → 触发后台摘要
- `write_interaction(query, response, event_type, **kwargs) -> InteractionResult` — 单对交互写入
- `get_history(limit: int) -> list[MemoryEvent]` — 过滤 daily_summary 后的历史事件
- `get_event_type(event_id: str) -> str | None` — O(1) 按 ID 查找

**Inflight 防护设计：**

```python
class MemoryLifecycle:
    def __init__(self, ...):
        self._inflight_summaries: set[str] = set()
        self._inflight_lock = asyncio.Lock()

    async def _trigger_background_summarize(self, date_key: str) -> None:
        async with self._inflight_lock:
            if date_key in self._inflight_summaries:
                return
            self._inflight_summaries.add(date_key)
        self._bg.spawn(self._background_summarize(date_key))
```

`_background_summarize` 完成后从 `_inflight_summaries` 移除 `date_key`（finally 块保证）。

### store.py — MemoryBankStore

瘦身为 Facade，仅做依赖组装 + 委托：

```python
class MemoryBankStore:
    store_name = "memory_bank"
    requires_embedding = True
    requires_chat = True
    supports_interaction = True

    def __init__(self, data_dir, embedding_model=None, chat_model=None, **kwargs):
        self._config = MemoryBankConfig()
        self._index = FaissIndex(data_dir, self._config.embedding_dim)
        self._bg = BackgroundTaskRunner(self._config)
        embed_client = EmbeddingClient(embedding_model) if embedding_model else None
        llm = LlmClient(chat_model) if chat_model else None
        summarizer = Summarizer(llm, self._index, self._config) if llm else None
        self._lifecycle = MemoryLifecycle(
            self._index, embed_client,
            ForgettingCurve(self._config),
            summarizer,
            self._config, self._bg,
        )
        self._retrieval = RetrievalPipeline(
            self._index, embed_client, self._config,
        ) if embed_client else None

    # MemoryStore Protocol 方法全部委托给 _lifecycle / _retrieval

    async def close(self) -> None:
        """关闭后台任务。MemoryModule 应在 shutdown 时调用。"""
        await self._bg.shutdown()
```

`close()` 由 `MemoryModule` 在应用 shutdown 时调用。`MemoryModule` 需新增 `close()` 方法，透传到 `_stores` 中每个 store 的 `close()`（若存在）。`MemoryStore` Protocol 中 **不强制** `close()` 方法（其他 store 可能不需要），`MemoryModule` 用 `hasattr` 检测。

## AGENTS.md 同步

### 删除（代码中不存在）

| 条目 | 原因 |
|------|------|
| `score = similarity × retention` | 实际评分 = FAISS 内积 + 说话人降权 |
| 名称匹配加分 `×1.3` | 无实现 |
| 时效性衰减 `最低 0.7` | 无实现 |
| `SUMMARY_WEIGHT = 0.8` | retrieval.py 中无此常量 |
| `PERSONALITY_SUMMARY_THRESHOLD = 2` | summarizer.py 无阈值，有数据即生成 |
| `OVERALL_PERSONALITY_THRESHOLD = 3` | 同上 |

### 新增

| 条目 | 值 | 位置 |
|------|-----|------|
| `DEFAULT_CHUNK_SIZE` | 1500（自适应回退值） | retrieval.py |
| `CHUNK_SIZE_MIN` | 200 | config.py |
| `CHUNK_SIZE_MAX` | 8192 | config.py |
| `FORGET_INTERVAL_SECONDS` | 300 | config.py |
| `shutdown_timeout_seconds` | 30.0 | config.py |

注意：`chunk_size` 配置项默认 `None`（自适应 P90×3），`DEFAULT_CHUNK_SIZE=1500` 仅在条目不足 10 时回退使用。

## 接口变更

| 位置 | 变更 | 影响 |
|------|------|------|
| `MemoryBankStore` | 新增 `async close()` | 需 `MemoryModule` 在 shutdown 时调用 |
| `MemoryModule` | 新增 `async close()` 透传到各 store | `app/api/main.py` 需在 shutdown handler 调用 |
| `MemoryStore` Protocol | **不变**（`close()` 不在 Protocol 中，`MemoryModule` 用 `hasattr` 检测） | 无 |
| `FaissIndex` | 文件从 `faiss_index.py` 重命名为 `index.py` | 更新所有 import 语句 |
| 各子组件 | 构造函数签名变更（增加 `config` 参数） | 内部影响，不暴露到 Store 层以上 |

## 接口兼容性

`MemoryStore` Protocol 不变，`MemoryBankStore` 的 `write/search/get_history/update_feedback/get_event_type/write_interaction` 方法签名不变。外部调用者（`MemoryModule.write/search/...`、`GraphQL resolvers`）无需修改。

## 测试策略

- 现有测试保持不变（测试 `MemoryStore` Protocol 行为和规则引擎）
- `BackgroundTaskRunner` 新增单元测试（spawn/shutdown/lifecycle/超时）
- `MemoryLifecycle` inflight 防护新增测试（并发写入同日期不重复提交摘要）
- `MemoryBankConfig` 新增测试（环境变量绑定、默认值）
- `MemoryBankStore.close()` 集成测试（shutdown 时后台任务正常取消）
- `MemoryModule.close()` 集成测试（透传到 store）
