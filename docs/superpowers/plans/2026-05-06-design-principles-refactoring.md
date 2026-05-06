# 设计原则重构实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 subagent-driven-development（推荐）逐任务实现此计划。步骤使用复选框（`- [ ]`）语法跟踪进度。

**目标：** 修复 memory 模块 SRP/DIP/OCP/ISP 违反。引入 Protocol 抽象层 + SearchEnricher + BackgroundWorker，MemoryModule 对外接口不变。

**架构：** MemoryBankStore 从直接 new 具体依赖改为构造器注入 Protocol 接口；搜索上下文注入提取为策略；后台任务提取为独立 Worker。MemoryStore Protocol 拆为通用层与交互扩展层。

**技术栈：** Python 3.14, typing.Protocol, Faiss, asyncio, pytest

---

## 文件结构

| 文件 | 职责 | 变更 |
|------|------|------|
| `app/memory/interfaces.py` | 全部 Protocol 定义 | 重写 |
| `app/memory/enricher.py`（新） | OverallContextEnricher | 创建 |
| `app/memory/worker.py`（新） | BackgroundWorker | 创建 |
| `app/memory/stores/memory_bank/store.py` | MemoryBankStore DI 化 | 重构 |
| `app/memory/memory.py` | _create_store 组装 DI 树 | 修改 |
| `app/memory/stores/memory_bank/*.py` + `components.py` | 加 Protocol import | 各加一行 |
| `tests/stores/test_enricher.py`（新） | OverallContextEnricher 测试 | 创建 |
| `tests/test_background_worker.py`（新） | BackgroundWorker 测试 | 创建 |
| `tests/stores/test_memory_bank_store.py` | 构造参数更新 | 修改 |

---

### Task 1：重写 interfaces.py——全部 Protocol

**文件：** `app/memory/interfaces.py`（重写）

- [ ] **步骤 1.1：写入全部 Protocol 定义**

```python
"""MemoryStore 结构化接口定义（Protocol）及所有子组件依赖抽象。"""

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.memory.schemas import (
        FeedbackData,
        InteractionResult,
        MemoryEvent,
        SearchResult,
    )


class MemoryStore(Protocol):
    """通用记忆存储接口。"""
    store_name: str

    async def write(self, event: MemoryEvent) -> str: ...
    async def search(self, query: str, top_k: int = 10) -> list[SearchResult]: ...
    async def get_history(self, limit: int = 10) -> list[MemoryEvent]: ...
    async def update_feedback(self, event_id: str, feedback: FeedbackData) -> None: ...
    async def get_event_type(self, event_id: str) -> str | None: ...


class InteractiveMemoryStore(MemoryStore, Protocol):
    """支持交互记录的扩展接口。"""
    async def write_interaction(
        self, query: str, response: str, event_type: str = "reminder",
    ) -> InteractionResult: ...


class VectorIndex(Protocol):
    """向量索引抽象（FaissIndex 契约）。"""
    async def load(self) -> None: ...
    async def save(self) -> None: ...
    async def add_vector(self, text: str, embedding: list[float],
                         timestamp: str, extra_meta: dict | None = None) -> int: ...
    async def search(self, query_emb: list[float], top_k: int) -> list[dict]: ...
    async def remove_vectors(self, faiss_ids: list[int]) -> None: ...
    def get_metadata(self) -> list[dict]: ...
    def get_metadata_by_id(self, faiss_id: int) -> dict | None: ...
    def get_extra(self) -> dict: ...
    def set_extra(self, extra: dict) -> None: ...
    @property
    def total(self) -> int: ...


class ForgettingStrategy(Protocol):
    """遗忘策略抽象。"""
    def maybe_forget(self, metadata: list[dict],
                     reference_date: str | None = None) -> list[int] | None: ...


class RetrievalStrategy(Protocol):
    """检索管道抽象。"""
    async def search(self, query: str, top_k: int = 5) -> list[dict]: ...


class FeedbackHandler(Protocol):
    """反馈处理抽象。"""
    async def update_feedback(self, event_id: str,
                              feedback: FeedbackData) -> None: ...


class SummarizationService(Protocol):
    """摘要/人格生成抽象。"""
    async def get_daily_summary(self, date_key: str) -> str | None: ...
    async def get_overall_summary(self) -> str | None: ...
    async def get_daily_personality(self, date_key: str) -> str | None: ...
    async def get_overall_personality(self) -> str | None: ...


class SearchEnricher(Protocol):
    """搜索结果上下文注入策略抽象。"""
    async def enrich(self, results: list[SearchResult],
                     extra: dict) -> list[SearchResult]: ...
```

- [ ] **步骤 1.2：lint + type check**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```

- [ ] **步骤 1.3：Commit**

```bash
git add app/memory/interfaces.py
git commit -m "refactor: define Protocol hierarchy for DI (MemoryStore/InteractiveMemoryStore/VectorIndex/etc)"
```

---

### Task 2：既有实现类加 Protocol import

**文件：** faiss_index.py, forget.py, retrieval.py, components.py, summarizer.py

各文件 TYPE_CHECKING 块追加对应 Protocol 的 import。无需改类定义——Python Protocol 是结构子类型，方法匹配即满足。

| 文件 | 加 import |
|------|-----------|
| `faiss_index.py` | `from app.memory.interfaces import VectorIndex` |
| `forget.py` | `from app.memory.interfaces import ForgettingStrategy` |
| `retrieval.py` | `from app.memory.interfaces import RetrievalStrategy` |
| `components.py` | `from app.memory.interfaces import FeedbackHandler` |
| `summarizer.py` | `from app.memory.interfaces import SummarizationService` |

- [ ] **步骤 2.1：5 个文件各加一行 import**
- [ ] **步骤 2.2：lint + type check**
- [ ] **步骤 2.3：Commit**

---

### Task 3：创建 OverallContextEnricher

**文件：** `app/memory/enricher.py`（创建）

- [ ] **步骤 3.1：写入 enricher.py**

```python
"""搜索结果上下文注入策略实现。"""

from app.memory.interfaces import SearchEnricher
from app.memory.schemas import SearchResult
from app.memory.stores.memory_bank.summarizer import GENERATION_EMPTY


class OverallContextEnricher:
    """注入 overall_summary + overall_personality 到搜索结果前置。

    通过可配置的 (extra_key, label) 对列表支持扩展。
    """

    def __init__(self, keys: list[tuple[str, str]] | None = None) -> None:
        """初始化 enricher。

        Args:
            keys: (extra_key, label) 对列表。
                  默认注入 overall_summary 和 overall_personality。
        """
        self._keys = keys or [
            ("overall_summary", "Overall summary of past memories"),
            ("overall_personality", "User vehicle preferences and habits"),
        ]

    async def enrich(
        self,
        results: list[SearchResult],
        extra: dict,
    ) -> list[SearchResult]:
        """在 results 前置全局上下文摘要/人格信息。"""
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

- [ ] **步骤 3.2：lint + type check**
- [ ] **步骤 3.3：Commit**

---

### Task 4：创建 BackgroundWorker

**文件：** `app/memory/worker.py`（创建）

- [ ] **步骤 4.1：写入 worker.py**

```python
"""后台记忆维护任务调度器。"""

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.memory.interfaces import SummarizationService, VectorIndex
    from app.models.embedding import EmbeddingModel

logger = logging.getLogger(__name__)


class BackgroundWorker:
    """后台记忆维护任务调度器。

    从 MemoryBankStore._background_summarize 提取，统一管理 async task 生命周期。
    错误内部 logging 记录，不 propagation 到 caller。
    """

    def __init__(
        self,
        index: VectorIndex,
        summarizer: SummarizationService | None = None,
        encoder: EmbeddingModel | None = None,
    ) -> None:
        self._index = index
        self._summarizer = summarizer
        self._encoder = encoder
        self._tasks: set[asyncio.Task[None]] = set()

    def schedule_summarize(self, date_key: str) -> None:
        """调度后台摘要任务。"""
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

- [ ] **步骤 4.2：lint + type check**
- [ ] **步骤 4.3：Commit**

---

### Task 5：重构 MemoryBankStore——DI 化

**文件：** `app/memory/stores/memory_bank/store.py`

**变更概要：**
- 构造器改为接收已组装好的 Protocol 对象，不再直接 new
- `write`/`write_interaction` 仍需要 `EmbeddingModel` 做文本编码——作为单独依赖注入
- `search` 中上下文注入委托给 `SearchEnricher`
- 删除 `_background_summarize`（移到 BackgroundWorker）
- 保留 `requires_embedding = True`, `requires_chat = True` 作为工厂元数据

- [ ] **步骤 5.1：实现新 MemoryBankStore**

核心签名：

```python
class MemoryBankStore:
    store_name = "memory_bank"
    requires_embedding = True
    requires_chat = True

    def __init__(
        self,
        index: VectorIndex,
        retrieval: RetrievalStrategy,
        embedding_model: EmbeddingModel,       # write 编码用
        enricher: SearchEnricher | None = None,
        forgetting: ForgettingStrategy | None = None,
        feedback: FeedbackHandler | None = None,
        background: BackgroundWorker | None = None,
    ) -> None: ...
```

各方法实现对照表：

| 原方法 | 新实现差异 |
|--------|-----------|
| `write` | `emb = await self._embedding_model.encode(text)` → 用注入的 embedding_model |
| `write_interaction` | 同上 |
| `search` | 删除末尾 prepend 硬编码 → `if self._enricher: out = await self._enricher.enrich(out, self._index.get_extra())` |
| `_background_summarize` | 删除整段 |
| `get_history` | 不变 |
| `get_event_type` | 不变 |
| `update_feedback` | 不变 |

**警告：** `MemoryBankStore` 已有 `_forgetting_enabled` 环境变量控制和遗忘元数据，DI 后 `ForgettingStrategy` 参数为 `None` 时整段跳过，所以 `_forgetting_enabled` 检查移到 `ForgettingCurve.__init__` 或仍保留在 MemoryBankStore——后者更简单，保留 `_forgetting_enabled` 判断。

- [ ] **步骤 5.2：lint + type check**
- [ ] **步骤 5.3：Commit**

---

### Task 6：更新 MemoryModule._create_store

**文件：** `app/memory/memory.py`

- [ ] **步骤 6.1：重写 `_create_store`**

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
        embedding_model=embedding,
        enricher=enricher,
        forgetting=forgetting,
        feedback=feedback,
        background=background,
    )
```

**import 追加：** `from app.memory.enricher import OverallContextEnricher` 和 `from app.memory.worker import BackgroundWorker`（放到现有 import 块中）。

- [ ] **步骤 6.2：更新 `write_interaction` 类型检查**

将：

```python
if not getattr(store, "supports_interaction", False):
    raise NotImplementedError(...)
```

改为：

```python
if not isinstance(store, InteractiveMemoryStore):
    msg = f"Store does not support write_interaction"
    raise NotImplementedError(msg)
```

需在文件头 `from app.memory.interfaces import InteractiveMemoryStore`（运行时 import，因为 `isinstance` 在运行时执行）。

- [ ] **步骤 6.3：lint + type check + test**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
uv run pytest -x --ff
```

预期：现有测试因构造参数变化会失败——Task 8 修复。

- [ ] **步骤 6.4：Commit**

---

### Task 7：新组件测试

- [ ] **步骤 7.1：测试 OverallContextEnricher**

**文件：** `tests/stores/test_enricher.py`

```python
"""Test OverallContextEnricher."""

import pytest
from app.memory.enricher import OverallContextEnricher
from app.memory.schemas import SearchResult


class TestOverallContextEnricher:
    """Given an enricher with default keys."""

    @pytest.fixture
    def enricher(self):
        return OverallContextEnricher()

    async def test_empty_extra_returns_results_unchanged(self, enricher):
        results = [SearchResult(event={"content": "a"}, score=1.0)]
        out = await enricher.enrich(results, {})
        assert out == results

    async def test_prepends_summary_when_present(self, enricher):
        results = [SearchResult(event={"content": "a"}, score=1.0)]
        extra = {"overall_summary": "User likes sport mode"}
        out = await enricher.enrich(results, extra)
        assert len(out) == 2
        assert "User likes sport mode" in out[0].event["content"]
        assert out[1].event["content"] == "a"

    async def test_skips_GENERATION_EMPTY(self, enricher):
        results = [SearchResult(event={"content": "a"}, score=1.0)]
        extra = {"overall_summary": "GENERATION_EMPTY"}
        out = await enricher.enrich(results, extra)
        assert len(out) == 1
        assert out[0] == results[0]

    async def test_custom_keys(self):
        enricher = OverallContextEnricher(keys=[("custom_key", "Custom label")])
        results = [SearchResult(event={"content": "x"}, score=0.5)]
        extra = {"custom_key": "value"}
        out = await enricher.enrich(results, extra)
        assert "Custom label: value" in out[0].event["content"]
```

- [ ] **步骤 7.2：运行测试确认通过**

```bash
uv run pytest tests/stores/test_enricher.py -v
```

- [ ] **步骤 7.3：测试 BackgroundWorker**

**文件：** `tests/test_background_worker.py`

思路：mock `SummarizationService` 和 `EmbeddingModel`，验证 `schedule_summarize` 触发对应调用。

```python
"""Test BackgroundWorker."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.memory.worker import BackgroundWorker


class TestBackgroundWorker:
    """Given a worker with mocked dependencies."""

    @pytest.fixture
    def mock_index(self):
        idx = MagicMock()
        idx.save = AsyncMock()
        idx.add_vector = AsyncMock(return_value=42)
        return idx

    @pytest.fixture
    def mock_summarizer(self):
        s = MagicMock()
        s.get_daily_summary = AsyncMock(return_value="Daily text")
        s.get_overall_summary = AsyncMock(return_value="Overall")
        s.get_daily_personality = AsyncMock(return_value="Personality")
        s.get_overall_personality = AsyncMock(return_value="Overall P")
        return s

    @pytest.fixture
    def mock_encoder(self):
        e = MagicMock()
        e.encode = AsyncMock(return_value=[0.1, 0.2, 0.3])
        return e

    @pytest.fixture
    def worker(self, mock_index, mock_summarizer, mock_encoder):
        return BackgroundWorker(mock_index, mock_summarizer, mock_encoder)

    async def test_schedule_triggers_summary_pipeline(
        self, worker, mock_summarizer, mock_encoder, mock_index,
    ):
        worker.schedule_summarize("2026-05-06")
        await asyncio.sleep(0.1)  # 让后台 task 跑完
        mock_summarizer.get_daily_summary.assert_awaited_once_with("2026-05-06")
        mock_encoder.encode.assert_awaited_once()
        mock_index.add_vector.assert_awaited_once()
        mock_summarizer.get_overall_summary.assert_awaited_once()
        mock_summarizer.get_daily_personality.assert_awaited_once_with("2026-05-06")
        mock_summarizer.get_overall_personality.assert_awaited_once()

    async def test_no_encoder_skips_encode(self, mock_index, mock_summarizer):
        worker = BackgroundWorker(mock_index, mock_summarizer, encoder=None)
        worker.schedule_summarize("2026-05-06")
        await asyncio.sleep(0.1)
        mock_index.add_vector.assert_not_awaited()
```

注意：需加 `import asyncio`。

- [ ] **步骤 7.4：运行测试确认通过**

```bash
uv run pytest tests/stores/test_enricher.py tests/test_background_worker.py -v
```

- [ ] **步骤 7.5：Commit**

---

### Task 8：更新既有测试适配新构造参数

**文件：** `tests/stores/test_memory_bank_store.py`（及 `conftest.py` 若 fixture 创建 MemoryBankStore）

**思路：** 搜索 test 文件中 `MemoryBankStore(` 调用点，将构造参数从 `(data_dir, embedding_model=..., chat_model=...)` 改为新格式。

使用 `FaissIndex`, `RetrievalPipeline`, `ForgettingCurve`, `FeedbackManager`, `OverallContextEnricher` 的直接实例（这些已有测试覆盖，不在本重构范围内）。

典型 fixture 改造：

```python
# 旧
store = MemoryBankStore(data_dir=tmp_path, embedding_model=embedding_model, chat_model=chat_model)

# 新
index = FaissIndex(tmp_path)
retrieval = RetrievalPipeline(index, embedding_model)
forgetting = ForgettingCurve()
feedback = FeedbackManager(tmp_path)
enricher = OverallContextEnricher()
llm = LlmClient(chat_model)
summarizer = Summarizer(llm, index)
background = BackgroundWorker(index, summarizer, embedding_model)

store = MemoryBankStore(
    index=index,
    retrieval=retrieval,
    embedding_model=embedding_model,
    enricher=enricher,
    forgetting=forgetting,
    feedback=feedback,
    background=background,
)
```

- [ ] **步骤 8.1：搜索所有 `MemoryBankStore(` 调用点并更新**
- [ ] **步骤 8.2：全量测试**

```bash
uv run pytest -x --ff
```

预期：全部通过（新组件测试 + 既有测试）。

- [ ] **步骤 8.3：Commit**

---

### 自检清单

计划编写完成后：

1. 浏览设计文档每个需求，确认有对应 task 覆盖
2. 搜索 plan 中占位符（TODO/TBD/后续实现）
3. 检查跨 task 类型/方法名一致性
