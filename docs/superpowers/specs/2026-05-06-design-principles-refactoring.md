# 设计原则违反分析与重构方案

## 概述

本文档分析知行车秘项目核心模块 `app/memory/` 对六项面向对象设计原则（SOLID + 迪米特法则）的违反情况，并给出架构解耦重构方案。

## 当前架构

```
MemoryModule (Facade, 统一接口)
  └── MemoryBankStore (MemoryStore 实现)
        ├── FaissIndex (向量索引 + 元数据持久化)
        ├── ForgettingCurve (遗忘曲线)
        ├── FeedbackManager (反馈 + 策略权重)
        ├── RetrievalPipeline (四阶段检索管道)
        ├── LlmClient (LLM 薄封装)
        └── Summarizer (摘要/人格生成)
```

## 违反分析

### SRP — 单一职责原则

| 位置 | 问题 | 严重程度 |
|------|------|---------|
| `MemoryBankStore` (store.py:42-239) | 上帝类。兼管 7 项职责：写入编排、搜索编排、后台任务调度、上下文注入、遗忘触发、反馈委托、状态加载/保存 | 严重 |
| `_input_to_context_dict` (mutation.py:68-118) | 50 行穷举 dict 转换，兼管嵌套结构全部字段 | 中等 |

### DIP — 依赖倒置原则

| 位置 | 问题 | 严重程度 |
|------|------|---------|
| `MemoryBankStore.__init__` | 直接 `new` 具体依赖：`FaissIndex()`、`ForgettingCurve()`、`FeedbackManager()`、`RetrievalPipeline(self._index, ...)` | 严重 |
| `RetrievalPipeline.__init__` | 直接接收 `FaissIndex` 具体类而非抽象接口 | 中等 |
| `Summarizer.__init__` | 直接依赖 `LlmClient` + `FaissIndex` 具体类 | 中等 |

### OCP — 开闭原则

| 位置 | 问题 | 严重程度 |
|------|------|---------|
| `MemoryBankStore.search()` | 上下文注入逻辑 hardcode（overall_summary + overall_personality），新增源须改 search 方法 | 中等 |
| `RetrievalPipeline` | 400 行四阶段管道内嵌全部检索逻辑，新增阶段须改此类 | 中等 |

### ISP — 接口隔离原则

| 位置 | 问题 | 严重程度 |
|------|------|---------|
| `MemoryStore` Protocol | 含 `write_interaction`，不支持交互的 store 亦须 stub 实现 | 中等 |

### LoD — 迪米特法则

| 位置 | 问题 | 严重程度 |
|------|------|---------|
| `_to_gql_preset` | 深度链 `p.get("context",{}).get("spatial",{}).get("destination")` | 轻度 |
| `_input_to_context_dict` | 深度访问 `input_obj.spatial.current_location.latitude` | 轻度 |

### LSP — 里氏替换原则

无违反。仅一种 store 实现，无继承层次问题。

## 重构方案

### 选择：架构解耦（方案甲）

**方向**：完整 DI + 职责提取。引入 Protocol 抽象层 + SearchEnricher + BackgroundWorker，不改 MemoryModule 对外接口。

### Protocol 层次（ISP 修复）

```
MemoryStore (Protocol)
├── write(event) → str
├── search(query, top_k) → list[SearchResult]
├── get_history(limit) → list[MemoryEvent]
├── get_event_type(event_id) → str | None
└── update_feedback(event_id, feedback) → None

InteractiveMemoryStore (MemoryStore)
└── write_interaction(query, response, event_type) → InteractionResult
```

`MemoryModule.write_interaction` 以 `isinstance(store, InteractiveMemoryStore)` 判断支持与否。

> **为何选 isinstance 而非 supports_interaction flag**：Facade 层的 capability 检查只需区分两个 Protocol 级别，运行时类型检查是最直白的表达。若后续出现第三种级别，可改用 `supports_interaction: bool` 属性，但当前不 YAGNI。

### 依赖注入接口（DIP 修复）

```
VectorIndex (Protocol)
├── load(), save()
├── add_vector(text, embedding, timestamp, extra_meta) → int
├── search(query_emb, top_k) → list[dict]
├── remove_vectors(faiss_ids)
├── get_metadata() → list[dict]
├── get_extra() → dict
└── total → int

ForgettingStrategy (Protocol)
└── maybe_forget(metadata, reference_date) → list[int] | None

RetrievalStrategy (Protocol)
└── search(query, top_k) → list[dict]

FeedbackHandler (Protocol)
└── update_feedback(event_id, feedback) → None

SummarizationService (Protocol)
├── get_daily_summary(date_key) → str | None
├── get_overall_summary() → str | None
├── get_daily_personality(date_key) → str | None
└── get_overall_personality() → str | None

SearchEnricher (Protocol)
└── enrich(results, extra) → list[SearchResult]
```

现有实现类加 Protocol 继承标记，不改内部逻辑：
- `FaissIndex implements VectorIndex`
- `ForgettingCurve implements ForgettingStrategy`
- `RetrievalPipeline implements RetrievalStrategy`
- `FeedbackManager implements FeedbackHandler`
- `Summarizer + LlmClient` 组合为 `SummarizationService`

### SearchEnricher（OCP 修复）

将 `MemoryBankStore.search()` 末尾的上下文注入逻辑提取为策略：

```python
class OverallContextEnricher:
    """注入 overall_summary + overall_personality。"""

    def __init__(self, keys: list[tuple[str, str]] | None = None):
        self._keys = keys or [
            ("overall_summary", "Overall summary of past memories"),
            ("overall_personality", "User vehicle preferences and habits"),
        ]

    async def enrich(
        self,
        results: list[SearchResult],
        extra: dict,
    ) -> list[SearchResult]:
        """在 results 前置全局上下文。"""
        prepend = []
        for key, label in self._keys:
            val = extra.get(key, "")
            if val and val != GENERATION_EMPTY:
                prepend.append(f"{label}: {val}")
        if not prepend:
            return results
        out: list[SearchResult] = []
        out.append(
            SearchResult(
                event={"content": "\n".join(prepend), "type": "overall_context"},
                score=float("inf"),
                source="overall",
            )
        )
        top_k = len(results)
        out.extend(results[: max(0, top_k - 1)])
        return out
```

新增上下文源只需写新 Enricher 类，传参给 `MemoryBankStore`，不改 search。

### BackgroundWorker（SRP 拆分）

将从 `MemoryBankStore._background_summarize` 迁移后台任务生命周期管理：

```python
class BackgroundWorker:
    """后台记忆维护任务调度器。"""

    def __init__(
        self,
        index: VectorIndex,
        summarizer: SummarizationService | None,
        encoder: EmbeddingService | None = None,
    ):
        self._index = index
        self._summarizer = summarizer
        self._encoder = encoder
        self._tasks: set[asyncio.Task] = set()

    def schedule_summarize(self, date_key: str) -> None:
        """调度后台摘要任务。错误内部 logging，不 propagation。"""
        task = asyncio.create_task(self._run_summarize(date_key))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_summarize(self, date_key: str) -> None:
        if not self._summarizer or not self._encoder:
            return
        try:
            text = await self._summarizer.get_daily_summary(date_key)
            if text:
                emb = await self._encoder.encode(text)
                await self._index.add_vector(
                    text, emb, f"{date_key}T00:00:00",
                    {"type": "daily_summary", "source": f"summary_{date_key}"},
                )
                await self._index.save()
            await self._summarizer.get_overall_summary()
            await self._summarizer.get_daily_personality(date_key)
            await self._summarizer.get_overall_personality()
            await self._index.save()
        except Exception:
            logger.exception("background summarization failed")
```

### MemoryBankStore 最终形态

```python
class MemoryBankStore(InteractiveMemoryStore):
    store_name = "memory_bank"
    requires_embedding = True   # 工厂元数据，非 Protocol 成员
    requires_chat = True

    def __init__(
        self,
        index: VectorIndex,
        retrieval: RetrievalStrategy,
        enricher: SearchEnricher | None = None,
        forgetting: ForgettingStrategy | None = None,
        feedback: FeedbackHandler | None = None,
        background: BackgroundWorker | None = None,
    ):
        self._index = index
        self._retrieval = retrieval
        self._enricher = enricher
        self._forgetting = forgetting
        self._feedback = feedback
        self._background = background

    async def write(self, event):
        await self._index.load()
        fid = await self._index.add_vector(...)
        if self._forgetting:
            ...  # 遗忘触发
        await self._index.save()
        if self._background:
            self._background.schedule_summarize(date_key)
        return str(fid)

    async def search(self, query, top_k):
        await self._index.load()
        results = await self._retrieval.search(query, top_k)
        if self._enricher:
            results = await self._enricher.enrich(results, self._index.get_extra())
        return results
```

### MemoryModule._create_store 更新

```python
def _create_store(self, mode: MemoryMode) -> MemoryStore:
    store_cls = _STORES_REGISTRY[mode]
    data_dir = self._data_dir

    index: VectorIndex = FaissIndex(data_dir)

    embedding = self._embedding_model
    if embedding is None and getattr(store_cls, "requires_embedding", False):
        embedding = get_cached_embedding_model()

    chat = self._chat_model
    if chat is None and getattr(store_cls, "requires_chat", False):
        chat = get_chat_model()

    retrieval = RetrievalPipeline(index, embedding)
    forgetting = ForgettingCurve()
    feedback = FeedbackManager(data_dir)

    summarizer_svc = None
    background = None
    if chat:
        llm = LlmClient(chat)
        summarizer_svc = Summarizer(llm, index)
        background = BackgroundWorker(index, summarizer_svc, embedding)

    enricher = OverallContextEnricher()

    return MemoryBankStore(
        index=index,
        retrieval=retrieval,
        enricher=enricher,
        forgetting=forgetting,
        feedback=feedback,
        background=background,
    )
```

## 变更清单

| 文件 | 变更类型 | 内容 |
|------|---------|------|
| `interfaces.py` | 新增/修改 | `MemoryStore`, `InteractiveMemoryStore`, `VectorIndex`, `ForgettingStrategy`, `RetrievalStrategy`, `FeedbackHandler`, `SummarizationService`, `SearchEnricher` |
| `enricher.py`（新） | 新增 | `OverallContextEnricher` |
| `worker.py`（新） | 新增 | `BackgroundWorker` |
| `store.py` | 修改 | `MemoryBankStore` 构造器+方法 |
| `memory.py` | 修改 | `_create_store`, `write_interaction` 检查 |
| `components.py` | 不变 | 已有 `FeedbackManager` 不变 |
| 各 store 子模块 | 加 Protocol 标记 | `FaissIndex`, `ForgettingCurve` 等加 `implements` 标注 |

## 不变的内容

- `MemoryModule` 对外接口不变
- 除 `store.py` 外所有子组件实现逻辑不变
- `Mutation`/`Query` resolver 不变
- 测试框架不变，仅更新构造参数签名

## 未处理的违反

- LoD 违反（`_to_gql_preset`, `_input_to_context_dict`）——轻度，不影响扩展性，暂不处理。
