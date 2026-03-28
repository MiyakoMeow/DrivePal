# Memory Backend Types Refactoring - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 Pydantic 模型替代裸 dict，统一记忆后端接口签名，修复 P0 Bug，消除代码重复。

**Architecture:** 新增 `schemas.py` 定义 `MemoryEvent`、`SearchResult`、`FeedbackData` 等 Pydantic 模型。将 `write()` 默认实现和 `_keyword_search()` 提取到 `BaseMemoryStore`。所有 Store 的 `search()` 统一返回 `list[SearchResult]`。`MemoryModule` 对外暴露类型化接口，消费者适配 Pydantic 对象。

**Tech Stack:** Python 3.13, Pydantic (已存在于项目依赖), pytest

**Spec:** `docs/superpowers/specs/2026-03-28-memory-backend-types-design.md`

**Test command:** `pytest tests/ -v`
**Lint command:** `ruff check app/ tests/`
**Format command:** `ruff format --check app/ tests/`

---

## File Structure

| 文件 | 职责 | 操作 |
|---|---|---|
| `app/memory/schemas.py` | Pydantic 数据模型 | 新增 |
| `app/memory/interfaces.py` | MemoryStore 抽象接口 | 修改 |
| `app/memory/stores/base.py` | BaseMemoryStore 基类（默认实现） | 修改 |
| `app/memory/stores/keyword_store.py` | 关键词匹配 Store（简化） | 修改 |
| `app/memory/stores/llm_store.py` | LLM 语义判断 Store | 修改 |
| `app/memory/stores/embedding_store.py` | 向量相似度 Store | 修改 |
| `app/memory/stores/memory_bank_store.py` | 记忆库 Store（修复 Bug） | 修改 |
| `app/memory/memory.py` | MemoryModule 门面 | 修改 |
| `app/memory/__init__.py` | 导出 | 修改 |
| `app/agents/workflow.py` | Agent 工作流 | 修改 |
| `app/api/main.py` | FastAPI 入口 | 修改 |
| `tests/test_schemas.py` | Schemas 单元测试 | 新增 |
| `tests/test_memory_store_contract.py` | 契约测试 | 修改 |
| `tests/test_memory_module_facade.py` | 门面测试 | 修改 |
| `tests/test_memory_bank.py` | 集成测试 | 修改 |
| `tests/stores/test_keyword_store.py` | 关键词 Store 测试 | 修改 |
| `tests/stores/test_llm_store.py` | LLM Store 测试 | 修改 |
| `tests/stores/test_embedding_store.py` | Embedding Store 测试 | 修改 |
| `tests/stores/test_memory_bank_store.py` | MemoryBank Store 测试 | 修改 |

以下文件**无需修改**：`app/experiment/runner.py`, `run_experiment.py`, `app/storage/json_store.py`

---

### Task 1: Create Pydantic Schemas

**Files:**
- Create: `app/memory/schemas.py`
- Create: `tests/test_schemas.py`

- [ ] **Step 1: Write schema tests**

```python
"""MemoryEvent, SearchResult, FeedbackData 模型测试."""

from app.memory.schemas import MemoryEvent, SearchResult, FeedbackData, InteractionRecord


class TestMemoryEvent:
    def test_default_fields(self):
        event = MemoryEvent(content="hello")
        assert event.content == "hello"
        assert event.id == ""
        assert event.type == "reminder"

    def test_extra_fields_allowed(self):
        event = MemoryEvent(content="hello", memory_strength=1, date_group="2026-01-01")
        assert event.memory_strength == 1
        assert event.date_group == "2026-01-01"

    def test_model_dump(self):
        event = MemoryEvent(id="abc", content="hello", type="reminder")
        d = event.model_dump()
        assert d == {"id": "abc", "created_at": "", "content": "hello", "type": "reminder", "description": ""}

    def test_from_dict(self):
        event = MemoryEvent(**{"id": "x", "content": "y", "created_at": "2026-01-01"})
        assert event.id == "x"


class TestSearchResult:
    def test_default_fields(self):
        sr = SearchResult(event={"content": "hello"})
        assert sr.score == 0.0
        assert sr.source == "event"
        assert sr.interactions == []

    def test_to_public_excludes_internal(self):
        sr = SearchResult(event={"content": "hello"}, score=0.9, source="event", interactions=[{"q": "x"}])
        pub = sr.to_public()
        assert "content" in pub
        assert "score" not in pub
        assert "source" not in pub

    def test_to_public_includes_interactions(self):
        sr = SearchResult(event={"content": "hello"}, interactions=[{"q": "x"}])
        pub = sr.to_public()
        assert pub["interactions"] == [{"q": "x"}]

    def test_to_public_no_interactions(self):
        sr = SearchResult(event={"content": "hello"})
        pub = sr.to_public()
        assert "interactions" not in pub


class TestFeedbackData:
    def test_extra_fields(self):
        fb = FeedbackData(action="accept", modified_content="new")
        assert fb.modified_content == "new"

    def test_model_dump(self):
        fb = FeedbackData(event_id="x", action="accept")
        d = fb.model_dump()
        assert d["event_id"] == "x"


class TestInteractionRecord:
    def test_default_fields(self):
        ir = InteractionRecord(id="x", query="q", response="r")
        assert ir.event_id == ""
        assert ir.memory_strength == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_schemas.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Implement schemas**

Create `app/memory/schemas.py`:

```python
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MemoryEvent(BaseModel):
    id: str = ""
    created_at: str = ""
    content: str = ""
    type: str = "reminder"
    description: str = ""
    model_config = ConfigDict(extra="allow")


class InteractionRecord(BaseModel):
    id: str = ""
    event_id: str = ""
    query: str = ""
    response: str = ""
    timestamp: str = ""
    memory_strength: int = 1
    last_recall_date: str = ""


class FeedbackData(BaseModel):
    event_id: str = ""
    action: str = ""
    type: str = "default"
    timestamp: str = ""
    model_config = ConfigDict(extra="allow")


class SearchResult(BaseModel):
    event: dict = Field(default_factory=dict)
    score: float = 0.0
    source: str = "event"
    interactions: list[dict] = Field(default_factory=list)

    def to_public(self) -> dict:
        result = dict(self.event)
        if self.interactions:
            result["interactions"] = self.interactions
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_schemas.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add app/memory/schemas.py tests/test_schemas.py
git commit -m "feat: add Pydantic schemas for memory events, search results, and feedback"
```

---

### Task 2: Update Interfaces and BaseMemoryStore

**Files:**
- Modify: `app/memory/interfaces.py`
- Modify: `app/memory/stores/base.py`
- Modify: `tests/test_memory_store_contract.py`

- [ ] **Step 1: Update interfaces.py**

Replace full content with:

```python
"""MemoryStore 抽象接口定义."""

from abc import ABC, abstractmethod

from app.memory.schemas import FeedbackData, MemoryEvent, SearchResult


class MemoryStore(ABC):
    """记忆存储抽象接口."""

    requires_embedding: bool = False
    requires_chat: bool = False
    supports_interaction: bool = False

    @property
    @abstractmethod
    def store_name(self) -> str:
        """存储名称，用于注册和路由."""
        pass

    @abstractmethod
    def write(self, event: MemoryEvent) -> str:
        """写入事件，返回 event_id."""
        pass

    @abstractmethod
    def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        """检索记忆，返回匹配的结果列表."""
        pass

    def get_history(self, limit: int = 10) -> list[MemoryEvent]:
        """获取历史记录，按时间倒序返回最近 limit 条."""
        raise NotImplementedError

    def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        """更新反馈，同时更新策略权重."""
        raise NotImplementedError

    def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str:
        """写入交互记录，返回 event_id."""
        raise NotImplementedError
```

- [ ] **Step 2: Update base.py**

Replace full content with:

```python
"""MemoryStore 基类，提供共享的 events_store 和通用逻辑."""

import uuid
from abc import ABC
from datetime import datetime

from app.memory.interfaces import MemoryStore
from app.memory.schemas import FeedbackData, MemoryEvent, SearchResult
from app.storage.json_store import JSONStore


class BaseMemoryStore(MemoryStore, ABC):
    """MemoryStore 基类."""

    requires_embedding: bool = False
    requires_chat: bool = False
    supports_interaction: bool = False

    def __init__(
        self,
        data_dir: str,
        embedding_model=None,
        chat_model=None,
    ) -> None:
        self.data_dir = data_dir
        self.events_store = JSONStore(data_dir, "events.json", list)
        self.strategies_store = JSONStore(data_dir, "strategies.json", dict)

    def _generate_id(self) -> str:
        return f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

    def write(self, event: MemoryEvent) -> str:
        event = event.model_copy(deep=True)
        event.id = self._generate_id()
        event.created_at = datetime.now().isoformat()
        self.events_store.append(event.model_dump())
        return event.id

    def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        events = self.events_store.read()
        matched = self._keyword_search(query, events)
        return [SearchResult(event=e) for e in matched[:top_k]]

    def _keyword_search(self, query: str, events: list[dict]) -> list[dict]:
        query_lower = query.lower()
        return [
            e for e in events
            if query_lower in e.get("content", "").lower()
            or query_lower in e.get("description", "").lower()
        ]

    def get_history(self, limit: int = 10) -> list[MemoryEvent]:
        events = self.events_store.read()
        if limit <= 0:
            return []
        return [MemoryEvent(**e) for e in events[-limit:]]

    def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        feedback.event_id = event_id
        feedback.timestamp = datetime.now().isoformat()
        feedback_store = JSONStore(self.data_dir, "feedback.json", list)
        feedback_store.append(feedback.model_dump())
        self._update_strategy(event_id, feedback.model_dump())

    def _update_strategy(self, event_id: str, feedback: dict) -> None:
        strategies = self.strategies_store.read()
        action = feedback.get("action")
        event_type = feedback.get("type", "default")

        if "reminder_weights" not in strategies:
            strategies["reminder_weights"] = {}

        if action == "accept":
            strategies["reminder_weights"][event_type] = min(
                strategies["reminder_weights"].get(event_type, 0.5) + 0.1, 1.0
            )
        elif action == "ignore":
            strategies["reminder_weights"][event_type] = max(
                strategies["reminder_weights"].get(event_type, 0.5) - 0.1, 0.1
            )

        self.strategies_store.write(strategies)

    def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str:
        event = MemoryEvent(
            content=response,
            type=event_type,
            description=query,
        )
        return self.write(event)
```

- [ ] **Step 3: Update contract tests**

Replace `tests/test_memory_store_contract.py`:

```python
"""MemoryStore 接口契约测试 - 验证所有实现满足统一接口."""

import pytest

from app.memory.schemas import FeedbackData, MemoryEvent, SearchResult


class TestMemoryStoreContract:
    """验证所有 MemoryStore 实现满足接口契约."""

    @pytest.fixture(params=["keyword", "llm_only", "embeddings", "memorybank"])
    def store(self, request, tmp_path):
        from app.memory.memory import MemoryModule

        mm = MemoryModule(str(tmp_path))
        return mm._get_store(request.param)

    def test_write_returns_string_id(self, store):
        event_id = store.write(MemoryEvent(content="test"))
        assert isinstance(event_id, str)
        assert len(event_id) > 0

    def test_write_then_search_returns_same_event(self, store):
        event_id = store.write(MemoryEvent(content="测试事件"))
        events = store.events_store.read()
        assert any(e["id"] == event_id for e in events)

    def test_search_returns_list_of_search_result(self, store):
        store.write(MemoryEvent(content="测试事件"))
        results = store.search("测试")
        assert isinstance(results, list)
        assert all(isinstance(r, SearchResult) for r in results)

    def test_get_history_returns_list_of_memory_event(self, store):
        store.write(MemoryEvent(content="事件1"))
        history = store.get_history(limit=10)
        assert isinstance(history, list)
        assert isinstance(history[0], MemoryEvent)

    def test_get_history_respects_limit(self, store):
        for i in range(5):
            store.write(MemoryEvent(content=f"事件{i}"))
        history = store.get_history(limit=3)
        assert len(history) == 3

    def test_update_feedback_updates_strategies(self, store):
        event_id = store.write(MemoryEvent(content="事件"))
        store.update_feedback(event_id, FeedbackData(action="accept", type="meeting"))
        strategies = store.strategies_store.read()
        assert "reminder_weights" in strategies
```

- [ ] **Step 4: Run contract tests — expect partial failures**

Run: `pytest tests/test_memory_store_contract.py -v`
Expected: Most PASS (keyword store inherits base), but some stores may fail (not yet updated)

- [ ] **Step 5: Commit**

```bash
git add app/memory/interfaces.py app/memory/stores/base.py tests/test_memory_store_contract.py
git commit -m "refactor: typed MemoryStore interface, BaseMemoryStore with shared write/search"
```

---

### Task 3: Simplify KeywordMemoryStore

**Files:**
- Modify: `app/memory/stores/keyword_store.py`
- Modify: `tests/stores/test_keyword_store.py`

- [ ] **Step 1: Simplify keyword_store.py**

Replace full content:

```python
"""关键词匹配检索 store."""

from app.memory.stores.base import BaseMemoryStore

_STORE_NAME = "keyword"


class KeywordMemoryStore(BaseMemoryStore):

    @property
    def store_name(self) -> str:
        return _STORE_NAME
```

All methods inherited from BaseMemoryStore: `write()`, `search()`, `get_history()`, `update_feedback()`, `write_interaction()`.

- [ ] **Step 2: Update keyword_store tests**

Replace `tests/stores/test_keyword_store.py`:

```python
"""Tests for KeywordMemoryStore."""

import pytest
from app.memory.schemas import FeedbackData, MemoryEvent, SearchResult
from app.memory.stores.keyword_store import KeywordMemoryStore


@pytest.fixture
def store(tmp_path):
    return KeywordMemoryStore(str(tmp_path))


class TestKeywordMemoryStore:
    def test_write_returns_event_id(self, store):
        event_id = store.write(MemoryEvent(content="测试事件"))
        assert isinstance(event_id, str)

    def test_write_then_search_returns_event(self, store):
        event_id = store.write(MemoryEvent(content="测试事件"))
        results = store.search("测试")
        assert len(results) == 1
        assert isinstance(results[0], SearchResult)
        assert results[0].event["id"] == event_id

    def test_search_case_insensitive(self, store):
        store.write(MemoryEvent(content="Hello World"))
        results = store.search("hello")
        assert len(results) == 1

    def test_search_no_match(self, store):
        store.write(MemoryEvent(content="测试事件"))
        results = store.search("不存在")
        assert len(results) == 0

    def test_search_matches_description(self, store):
        store.write(MemoryEvent(content="主内容", description="辅助描述"))
        results = store.search("辅助")
        assert len(results) == 1

    def test_get_history_returns_recent_events(self, store):
        for i in range(5):
            store.write(MemoryEvent(content=f"事件{i}"))
        history = store.get_history(limit=3)
        assert len(history) == 3
        assert all(isinstance(e, MemoryEvent) for e in history)

    def test_update_feedback_accept(self, store):
        event_id = store.write(MemoryEvent(content="事件"))
        store.update_feedback(event_id, FeedbackData(action="accept", type="meeting"))
        strategies = store.strategies_store.read()
        assert strategies["reminder_weights"]["meeting"] > 0.5

    def test_update_feedback_ignore(self, store):
        event_id = store.write(MemoryEvent(content="事件"))
        store.update_feedback(event_id, FeedbackData(action="ignore", type="meeting"))
        strategies = store.strategies_store.read()
        assert strategies["reminder_weights"]["meeting"] < 0.5

    def test_write_interaction_stores_query_as_description(self, store):
        store.write_interaction("查询内容", "响应内容")
        history = store.get_history(limit=1)
        assert history[0].content == "响应内容"
        assert history[0].description == "查询内容"
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/stores/test_keyword_store.py -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add app/memory/stores/keyword_store.py tests/stores/test_keyword_store.py
git commit -m "refactor: simplify KeywordMemoryStore to inherit all methods from base"
```

---

### Task 4: Update LLMOnlyMemoryStore

**Files:**
- Modify: `app/memory/stores/llm_store.py`
- Modify: `tests/stores/test_llm_store.py`

- [ ] **Step 1: Update llm_store.py**

Remove `write()` method (inherited from base). Update `search()` to return `list[SearchResult]`.

```python
"""LLM 语义判断检索 store."""

import json
import logging
import re
from typing import Optional, TYPE_CHECKING

from app.memory.schemas import MemoryEvent, SearchResult
from app.memory.stores.base import BaseMemoryStore

if TYPE_CHECKING:
    from app.models.chat import ChatModel

logger = logging.getLogger(__name__)

LLM_SEARCH_PROMPT = """你是一个语义相关性判断助手。

判断用户的查询与给定的事件描述是否语义相关。

查询: {query}

事件: {event_description}

请返回JSON格式:
{{"relevant": true/false, "reasoning": "简短原因"}}
"""


class LLMOnlyMemoryStore(BaseMemoryStore):

    requires_chat: bool = True

    def __init__(
        self,
        data_dir: str,
        embedding_model=None,
        chat_model: Optional["ChatModel"] = None,
    ):
        super().__init__(data_dir)
        self.chat_model = chat_model

    @property
    def store_name(self) -> str:
        return "llm_only"

    def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        if not self.chat_model:
            return []

        events = self.events_store.read()
        if not events:
            return []

        results = []
        for event in events:
            event_text = event.get("content", "") or event.get("description", "")
            prompt = LLM_SEARCH_PROMPT.format(query=query, event_description=event_text)

            try:
                response = self.chat_model.generate(prompt)
                json_match = re.search(r"\{.*?\}", response, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group())
                    if data.get("relevant"):
                        results.append(SearchResult(event=dict(event)))
            except Exception as e:
                logger.warning("LLM relevance check failed: %s", e, exc_info=True)
                continue

        return results[:top_k]
```

- [ ] **Step 2: Update tests**

Replace `tests/stores/test_llm_store.py`:

```python
"""Tests for LLMOnlyMemoryStore."""

from unittest.mock import MagicMock

import pytest
from app.memory.schemas import MemoryEvent, SearchResult
from app.memory.stores.llm_store import LLMOnlyMemoryStore


@pytest.fixture
def mock_chat_model():
    chat = MagicMock()
    chat.generate.return_value = '{"relevant": true, "reasoning": "测试"}'
    return chat


@pytest.fixture
def store(tmp_path, mock_chat_model):
    return LLMOnlyMemoryStore(str(tmp_path), chat_model=mock_chat_model)


@pytest.fixture
def store_without_llm(tmp_path):
    return LLMOnlyMemoryStore(str(tmp_path), chat_model=None)


class TestLLMOnlyMemoryStore:
    def test_write_returns_event_id(self, store):
        event_id = store.write(MemoryEvent(content="测试事件"))
        assert isinstance(event_id, str)

    def test_search_with_llm_returns_relevant(self, store):
        store.write(MemoryEvent(content="明天有会议"))
        results = store.search("有什么安排")
        assert len(results) == 1
        assert isinstance(results[0], SearchResult)

    def test_search_without_llm_returns_empty(self, store_without_llm):
        store_without_llm.write(MemoryEvent(content="测试事件"))
        results = store_without_llm.search("测试")
        assert results == []

    def test_search_no_events_returns_empty(self, store):
        results = store.search("测试")
        assert results == []
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/stores/test_llm_store.py -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add app/memory/stores/llm_store.py tests/stores/test_llm_store.py
git commit -m "refactor: LLMOnlyMemoryStore returns SearchResult, inherits write from base"
```

---

### Task 5: Update EmbeddingMemoryStore

**Files:**
- Modify: `app/memory/stores/embedding_store.py`
- Modify: `tests/stores/test_embedding_store.py`

- [ ] **Step 1: Update embedding_store.py**

Remove `write()` method. Update `search()` to return `list[SearchResult]`. Use base `_keyword_search` for fallback.

```python
"""向量相似度检索 store."""

from typing import Optional, TYPE_CHECKING

from app.memory.schemas import SearchResult
from app.memory.stores.base import BaseMemoryStore
from app.memory.utils import cosine_similarity

if TYPE_CHECKING:
    from app.models.embedding import EmbeddingModel


class EmbeddingMemoryStore(BaseMemoryStore):

    requires_embedding: bool = True

    def __init__(
        self,
        data_dir: str,
        embedding_model: Optional["EmbeddingModel"] = None,
        chat_model=None,
    ):
        super().__init__(data_dir)
        self.embedding_model = embedding_model

    @property
    def store_name(self) -> str:
        return "embeddings"

    def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        if self.embedding_model is None:
            return super().search(query, top_k=top_k)

        query_vector = self.embedding_model.encode(query)
        events = self.events_store.read()
        if not events:
            return []

        event_texts = [event.get("content", "") for event in events]
        all_embeddings = self.embedding_model.batch_encode(event_texts)

        results = []
        for event, event_vector in zip(events, all_embeddings):
            similarity = cosine_similarity(query_vector, event_vector)
            if similarity > 0.7:
                results.append(SearchResult(event=dict(event), score=similarity))

        return results[:top_k]
```

- [ ] **Step 2: Update tests**

Replace `tests/stores/test_embedding_store.py`:

```python
"""Tests for EmbeddingMemoryStore."""

from unittest.mock import MagicMock

import pytest
from app.memory.schemas import MemoryEvent, SearchResult
from app.memory.stores.embedding_store import EmbeddingMemoryStore


@pytest.fixture
def mock_embedding_model():
    model = MagicMock()
    model.encode.return_value = [0.1] * 128
    model.batch_encode.return_value = [[0.1] * 128] * 10
    return model


@pytest.fixture
def store(tmp_path, mock_embedding_model):
    return EmbeddingMemoryStore(str(tmp_path), embedding_model=mock_embedding_model)


@pytest.fixture
def store_without_embedding(tmp_path):
    return EmbeddingMemoryStore(str(tmp_path), embedding_model=None)


class TestEmbeddingMemoryStore:
    def test_write_returns_event_id(self, store):
        event_id = store.write(MemoryEvent(content="测试事件"))
        assert isinstance(event_id, str)

    def test_search_with_embedding(self, store):
        store.write(MemoryEvent(content="明天有会议"))
        results = store.search("有什么安排")
        assert len(results) == 1
        assert isinstance(results[0], SearchResult)

    def test_search_without_embedding_falls_back_to_keyword(
        self, store_without_embedding
    ):
        store_without_embedding.write(MemoryEvent(content="测试事件"))
        results = store_without_embedding.search("测试")
        assert len(results) == 1

    def test_search_no_events_returns_empty(self, store):
        results = store.search("测试")
        assert results == []
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/stores/test_embedding_store.py -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add app/memory/stores/embedding_store.py tests/stores/test_embedding_store.py
git commit -m "refactor: EmbeddingMemoryStore returns SearchResult, uses base keyword fallback"
```

---

### Task 6: Fix MemoryBankStore (P0 Bug + SearchResult)

**Files:**
- Modify: `app/memory/stores/memory_bank_store.py`
- Modify: `tests/stores/test_memory_bank_store.py`
- Modify: `tests/test_memory_bank.py`

- [ ] **Step 1: Update memory_bank_store.py**

关键变更：
1. `write()` 接受 `MemoryEvent`，追加 MemoryBank 专有字段
2. `search()` 统一签名 `search(self, query, top_k=10)`，返回 `list[SearchResult]`
3. `_search_by_keyword` / `_search_by_embedding` 返回 `list[SearchResult]`
4. `_search_summaries` 返回 `list[SearchResult]`
5. `_expand_event_interactions` 操作 `SearchResult` 对象
6. **修复 P0 Bug**: `_strengthen_events` 删除第二次循环
7. `write_interaction` 接受/返回类型不变

由于文件较长（421 行），提供关键部分的差异而非完整文件。

**write() 方法替换为：**
```python
def write(self, event: MemoryEvent) -> str:
    event = event.model_copy(deep=True)
    event.id = self._generate_id()
    event.created_at = datetime.now().isoformat()
    today = date.today().isoformat()
    event.memory_strength = 1
    event.last_recall_date = today
    event.date_group = today
    self.events_store.append(event.model_dump())
    self._maybe_summarize(today)
    return event.id
```

**search() 方法替换为：**
```python
def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
    if not query.strip():
        return []
    events = self.events_store.read()
    summaries = self.summaries_store.read()
    daily_summaries = summaries.get("daily_summaries", {})
    if not events and not daily_summaries:
        return []
    if self.embedding_model is None:
        event_results = self._search_by_keyword(query, events, top_k)
    else:
        event_results = self._search_by_embedding(query, events, top_k)
    summary_results = self._search_summaries(query, daily_summaries, top_k=1)
    all_results = event_results + summary_results
    all_results.sort(key=lambda x: x.score, reverse=True)
    top_results = all_results[:top_k]
    return self._expand_event_interactions(top_results)
```

**_search_by_keyword 完整替换为：**
```python
def _search_by_keyword(
    self, query: str, events: list[dict], top_k: int
) -> list[SearchResult]:
    query_lower = query.lower()
    today = date.today()
    results = []
    for event in events:
        content = event.get("content", "").lower()
        if query_lower in content:
            strength = event.get("memory_strength", 1)
            last_recall = event.get("last_recall_date", today.isoformat())
            try:
                last_date = date.fromisoformat(last_recall)
                days_elapsed = (today - last_date).days
            except (ValueError, TypeError):
                days_elapsed = 0
            retention = forgetting_curve(days_elapsed, strength)
            results.append(SearchResult(event=dict(event), score=retention, source="event"))
    results.sort(key=lambda x: x.score, reverse=True)
    top_results = results[:top_k]
    self._strengthen_events([r.event for r in top_results])
    return top_results
```

**_search_by_embedding 完整替换为：**
```python
def _search_by_embedding(
    self, query: str, events: list[dict], top_k: int
) -> list[SearchResult]:
    assert self.embedding_model is not None
    query_vector = self.embedding_model.encode(query)
    event_texts = [event.get("content", "") for event in events]
    all_event_vectors = self.embedding_model.batch_encode(event_texts)
    today = date.today()
    results = []
    for event, event_vector in zip(events, all_event_vectors):
        similarity = cosine_similarity(query_vector, event_vector)
        strength = event.get("memory_strength", 1)
        last_recall = event.get("last_recall_date", today.isoformat())
        try:
            last_date = date.fromisoformat(last_recall)
            days_elapsed = (today - last_date).days
        except (ValueError, TypeError):
            days_elapsed = 0
        retention = forgetting_curve(days_elapsed, strength)
        score = similarity * retention
        if score > 0:
            results.append(SearchResult(event=dict(event), score=score, source="event"))
    results.sort(key=lambda x: x.score, reverse=True)
    top_results = results[:top_k]
    self._strengthen_events([r.event for r in top_results])
    return top_results
```

**_search_summaries 返回 `list[SearchResult]`：**
```python
results.append(SearchResult(
    event={"content": content, "date_group": date_group, "memory_strength": strength, "last_recall_date": last_recall},
    score=score,
    source="daily_summary",
))
```
排序改为 `results.sort(key=lambda x: x.score, reverse=True)`。

**_expand_event_interactions 替换为：**
```python
def _expand_event_interactions(self, results: list[SearchResult]) -> list[SearchResult]:
    interactions = self.interactions_store.read()
    interaction_by_event: dict[str, list[dict]] = {}
    for i in interactions:
        eid = i.get("event_id", "")
        if eid:
            interaction_by_event.setdefault(eid, []).append(i)
    for result in results:
        eid = result.event.get("id", "")
        result.interactions = interaction_by_event.get(eid, [])
    return results
```

**_strengthen_events 修复 P0 Bug — 删除第 188-191 行：**
```python
def _strengthen_events(self, matched_events: list[dict]) -> None:
    if not matched_events:
        return
    matched_ids = {e["id"] for e in matched_events if "id" in e}
    if not matched_ids:
        return
    all_events = self.events_store.read()
    today = date.today().isoformat()
    updated = False
    for event in all_events:
        if event.get("id") in matched_ids:
            event["memory_strength"] = event.get("memory_strength", 1) + 1
            event["last_recall_date"] = today
            updated = True
    if updated:
        self.events_store.write(all_events)
    self._strengthen_interactions(matched_ids)
```

**文件顶部添加 import：**
```python
from app.memory.schemas import MemoryEvent, SearchResult
```

- [ ] **Step 2: Update tests/stores/test_memory_bank_store.py**

关键变更：
- `store.write({"content": ...})` → `store.write(MemoryEvent(content=...))`
- `results[0]["content"]` → `results[0].event["content"]` 或 `results[0].to_public()["content"]`
- `results[0]["interactions"]` → `results[0].interactions`
- 添加 `from app.memory.schemas import MemoryEvent, SearchResult`

- [ ] **Step 3: Update tests/test_memory_bank.py**

关键变更：
- `results[0]["content"]` → `results[0].event["content"]`
- `results[0]["interactions"]` → `results[0].interactions`
- `results[0].get("interactions", [])` → `results[0].interactions`
- `results[0].get("_source")` → `results[0].source`
- `results[-1]["interactions"]` → `results[-1].interactions`
- `backend.write({"content": ...})` → `backend.write(MemoryEvent(content=...))`
- `results[0]["content"]` → `results[0].event["content"]`
- `len(results[0]["interactions"])` → `len(results[0].interactions)`
- 添加 `from app.memory.schemas import MemoryEvent`

- [ ] **Step 4: Run all memory bank tests**

Run: `pytest tests/test_memory_bank.py tests/stores/test_memory_bank_store.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add app/memory/stores/memory_bank_store.py tests/test_memory_bank.py tests/stores/test_memory_bank_store.py
git commit -m "fix: MemoryBankStore P0 double-increment bug, return SearchResult objects"
```

---

### Task 7: Update MemoryModule

**Files:**
- Modify: `app/memory/memory.py`
- Modify: `app/memory/__init__.py`
- Modify: `tests/test_memory_module_facade.py`

- [ ] **Step 1: Update memory.py**

Replace `MemoryModule` 类：

```python
"""统一记忆管理接口，Facade 模式 + 工厂注册表."""

import logging
from typing import Any, Optional, TYPE_CHECKING

from app.memory.interfaces import MemoryStore
from app.memory.schemas import FeedbackData, MemoryEvent, SearchResult
from app.memory.types import MemoryMode

if TYPE_CHECKING:
    from app.models.chat import ChatModel
    from app.models.embedding import EmbeddingModel

logger = logging.getLogger(__name__)

_STORES_REGISTRY: dict[MemoryMode, type[MemoryStore]] = {}


def register_store(name: MemoryMode, store_cls: type[MemoryStore]) -> None:
    if name in _STORES_REGISTRY:
        return
    _STORES_REGISTRY[name] = store_cls


def _import_all_stores() -> None:
    from app.memory.stores.keyword_store import KeywordMemoryStore
    from app.memory.stores.llm_store import LLMOnlyMemoryStore
    from app.memory.stores.embedding_store import EmbeddingMemoryStore
    from app.memory.stores.memory_bank_store import MemoryBankStore

    register_store(MemoryMode.KEYWORD, KeywordMemoryStore)
    register_store(MemoryMode.LLM_ONLY, LLMOnlyMemoryStore)
    register_store(MemoryMode.EMBEDDINGS, EmbeddingMemoryStore)
    register_store(MemoryMode.MEMORY_BANK, MemoryBankStore)


class MemoryModule:
    """统一记忆管理接口，Facade 模式."""

    def __init__(
        self,
        data_dir: str,
        embedding_model: Optional["EmbeddingModel"] = None,
        chat_model: Optional["ChatModel"] = None,
    ):
        _import_all_stores()
        self._stores: dict[MemoryMode, MemoryStore] = {}
        self._data_dir = data_dir
        self._embedding_model = embedding_model
        self._chat_model = chat_model
        self._default_mode: MemoryMode = MemoryMode.MEMORY_BANK

    @property
    def chat_model(self):
        if self._chat_model is None:
            from app.models.settings import get_chat_model

            self._chat_model = get_chat_model()
        return self._chat_model

    def _get_store(self, mode: MemoryMode) -> MemoryStore:
        if mode not in self._stores:
            self._stores[mode] = self._create_store(mode)
        return self._stores[mode]

    def _create_store(self, mode: MemoryMode) -> MemoryStore:
        if mode not in _STORES_REGISTRY:
            raise ValueError(
                f"Unknown mode: {mode}. Available: {list(_STORES_REGISTRY.keys())}"
            )
        store_cls = _STORES_REGISTRY[mode]
        kwargs: dict[str, Any] = {"data_dir": self._data_dir}
        if store_cls.requires_embedding:
            if self._embedding_model is None:
                from app.models.settings import get_embedding_model

                self._embedding_model = get_embedding_model()
            kwargs["embedding_model"] = self._embedding_model
        if store_cls.requires_chat:
            if self._chat_model is None:
                from app.models.settings import get_chat_model

                self._chat_model = get_chat_model()
            kwargs["chat_model"] = self._chat_model
        return store_cls(**kwargs)

    def set_default_mode(self, mode: MemoryMode) -> None:
        if mode not in _STORES_REGISTRY:
            raise ValueError(f"Unknown mode: {mode}")
        self._default_mode = mode

    def write(self, event: MemoryEvent) -> str:
        return self._get_store(self._default_mode).write(event)

    def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str:
        return self._get_store(self._default_mode).write_interaction(
            query, response, event_type
        )

    def search(self, query: str, mode: MemoryMode | None = None,
               top_k: int = 10) -> list[SearchResult]:
        target_mode = mode or self._default_mode
        return self._get_store(target_mode).search(query, top_k=top_k)

    def get_history(self, limit: int = 10) -> list[MemoryEvent]:
        return self._get_store(self._default_mode).get_history(limit)

    def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        self._get_store(self._default_mode).update_feedback(event_id, feedback)
```

- [ ] **Step 2: Update __init__.py**

```python
"""Memory module exports."""

from app.memory.memory import MemoryModule, register_store
from app.memory.schemas import FeedbackData, InteractionRecord, MemoryEvent, SearchResult

__all__ = [
    "MemoryModule",
    "register_store",
    "FeedbackData",
    "InteractionRecord",
    "MemoryEvent",
    "SearchResult",
]
```

- [ ] **Step 3: Update facade tests**

Replace `tests/test_memory_module_facade.py`:

```python
"""Tests for MemoryModule Facade."""

import pytest
from app.memory.schemas import MemoryEvent, SearchResult
from app.memory.memory import MemoryModule


@pytest.fixture
def mm(tmp_path):
    return MemoryModule(str(tmp_path))


class TestMemoryModuleFacade:
    def test_default_mode_is_memorybank(self, mm):
        assert mm._default_mode == "memorybank"

    def test_write_uses_default_mode(self, mm):
        mm.write(MemoryEvent(content="事件"))
        history = mm.get_history()
        assert len(history) == 1
        assert isinstance(history[0], MemoryEvent)

    def test_search_routes_to_correct_store(self, mm):
        mm.write(MemoryEvent(content="测试事件"))
        results = mm.search("测试", mode="keyword")
        assert len(results) == 1
        assert isinstance(results[0], SearchResult)

    def test_set_default_mode(self, mm):
        mm.set_default_mode("keyword")
        assert mm._default_mode == "keyword"

    def test_write_interaction_calls_memorybank(self, mm):
        interaction_id = mm.write_interaction("提醒我开会", "好的")
        assert isinstance(interaction_id, str)

    def test_write_interaction_for_non_memorybank(self, mm):
        mm.set_default_mode("keyword")
        interaction_id = mm.write_interaction("查询内容", "响应内容")
        assert isinstance(interaction_id, str)
        history = mm.get_history()
        assert len(history) == 1
        assert history[0].content == "响应内容"
        assert history[0].description == "查询内容"

    def test_search_returns_search_result_objects(self, mm):
        mm.write(MemoryEvent(content="特殊关键词事件"))
        results = mm.search("特殊关键词", mode="keyword")
        assert all(isinstance(r, SearchResult) for r in results)
        pub = results[0].to_public()
        assert "score" not in pub

    def test_get_history_returns_memory_event_objects(self, mm):
        mm.write(MemoryEvent(content="事件"))
        history = mm.get_history()
        assert all(isinstance(e, MemoryEvent) for e in history)
```

- [ ] **Step 4: Run facade + contract tests**

Run: `pytest tests/test_memory_module_facade.py tests/test_memory_store_contract.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add app/memory/memory.py app/memory/__init__.py tests/test_memory_module_facade.py
git commit -m "refactor: MemoryModule exposes typed interfaces, add registry dedup"
```

---

### Task 8: Update Consumers

**Files:**
- Modify: `app/agents/workflow.py`
- Modify: `app/api/main.py`

- [ ] **Step 1: Update AgentWorkflow._context_node**

在 `app/agents/workflow.py` 中，修改 `_context_node` 方法中搜索/历史的使用方式：

```python
def _context_node(self, state: AgentState) -> dict:
    messages = state.get("messages", [])
    if not messages:
        user_input = ""
    else:
        user_input = str(messages[-1].content)

    try:
        related_events = (
            self.memory_module.search(user_input, mode=self.memory_mode)
            if user_input
            else []
        )
    except Exception as e:
        logger.warning(f"Memory search failed: {e}")
        related_events = []

    try:
        if related_events:
            relevant_memories = [e.to_public() for e in related_events]
        else:
            relevant_memories = [
                e.model_dump() for e in self.memory_module.get_history()
            ]
    except ValueError as e:
        logger.warning(f"Memory get_history failed: {e}")
        relevant_memories = (
            [e.to_public() for e in related_events] if related_events else []
        )
    except Exception as e:
        logger.warning(f"Memory get_history failed: {e}")
        relevant_memories = (
            [e.to_public() for e in related_events] if related_events else []
        )

    prompt = f"""{SYSTEM_PROMPTS["context"]}

用户输入: {user_input}
历史记录: {json.dumps(relevant_memories, ensure_ascii=False)}

请输出JSON格式的上下文对象. """

    context = self._call_llm_json(prompt)
    context["related_events"] = relevant_memories
    context["relevant_memories"] = relevant_memories

    return {
        "context": context,
        "messages": state["messages"]
        + [HumanMessage(content=f"Context: {json.dumps(context)}")],
    }
```

- [ ] **Step 2: Update API /api/history endpoint**

```python
@app.get("/api/history")
async def history(limit: int = 10, mm: MemoryModule = Depends(get_memory_module)):
    try:
        events = mm.get_history(limit=limit)
        return {"history": [e.model_dump() for e in events]}
    except Exception as e:
        logger.error(f"History retrieval failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
```

- [ ] **Step 3: Update API /api/feedback endpoint**

```python
@app.post("/api/feedback")
async def feedback(
    request: FeedbackRequest, mm: MemoryModule = Depends(get_memory_module)
):
    try:
        from app.memory.schemas import FeedbackData

        feedback = FeedbackData(
            action=request.action,
            modified_content=request.modified_content,
        )
        mm.update_feedback(request.event_id, feedback)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Feedback failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
```

- [ ] **Step 4: Run API tests**

Run: `pytest tests/test_api.py -v`
Expected: PASS (如果无需 LLM) 或 SKIP

- [ ] **Step 5: Commit**

```bash
git add app/agents/workflow.py app/api/main.py
git commit -m "refactor: adapt consumers to typed MemoryModule interface"
```

---

### Task 9: Final Verification

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v --ignore=tests/test_settings.py --ignore=tests/test_experiment_runner.py`
Expected: ALL PASS

- [ ] **Step 2: Run lint**

Run: `ruff check app/ tests/`
Expected: No errors

- [ ] **Step 3: Run format check**

Run: `ruff format --check app/ tests/`
Expected: No formatting issues (if issues, run `ruff format app/ tests/`)

- [ ] **Step 4: Verify unchanged files**

确认以下文件未被修改：
- `app/experiment/runner.py`
- `run_experiment.py`
- `app/storage/json_store.py`

- [ ] **Step 5: Final commit (if any lint fixes needed)**

```bash
git add -A
git commit -m "chore: lint fixes"
```
