# MemoryModule 重构实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 MemoryModule 拆分为统一的 MemoryStore 接口 + 四种独立实现类，消除重复存储实例

**Architecture:** 使用 Facade 模式 + 工厂注册表，四种 store（Keyword/LLM/Embedding/MemoryBank）独立实现，统一通过 MemoryModule Facade 访问

**Tech Stack:** Python, pytest, JSONStore, LangChain

---

## 文件结构

```
app/memory/
├── __init__.py                    # 修改：导出 MemoryModule, register_store
├── interfaces.py                  # 新增：MemoryStore ABC
├── memory.py                      # 重构：Facade + 工厂注册表
├── memory_bank.py                 # 删除（迁移到 stores/）
├── utils.py                       # 保留：cosine_similarity
└── stores/
    ├── __init__.py                # 新增：导入所有 store 类
    ├── base.py                    # 新增：BaseMemoryStore
    ├── keyword_store.py           # 新增：KeywordMemoryStore
    ├── llm_store.py               # 新增：LLMOnlyMemoryStore
    ├── embedding_store.py         # 新增：EmbeddingMemoryStore
    └── memory_bank_store.py       # 新增：从 memory_bank.py 迁移

tests/
├── test_memory_store_contract.py   # 新增：接口契约测试
├── stores/                        # 新增：各 store 独立测试
│   ├── __init__.py
│   ├── test_keyword_store.py
│   ├── test_llm_store.py
│   ├── test_embedding_store.py
│   └── test_memory_bank_store.py
└── test_memory_module_facade.py   # 新增：Facade 路由测试
```

---

## 任务列表

### 任务 1: 创建接口层

**Files:**
- Create: `app/memory/interfaces.py`
- Create: `app/memory/stores/__init__.py`
- Create: `app/memory/stores/base.py`

- [ ] **Step 1: 创建 `app/memory/interfaces.py`**

```python
"""MemoryStore 抽象接口定义."""

from abc import ABC, abstractmethod


class MemoryStore(ABC):
    """记忆存储抽象接口."""

    @property
    @abstractmethod
    def store_name(self) -> str:
        """存储名称，用于注册和路由."""
        pass

    @abstractmethod
    def write(self, event: dict) -> str:
        """写入事件，返回 event_id."""
        pass

    @abstractmethod
    def search(self, query: str) -> list[dict]:
        """检索记忆，返回匹配的事件列表."""
        pass

    @abstractmethod
    def get_history(self, limit: int = 10) -> list[dict]:
        """获取历史记录，按时间倒序返回最近 limit 条."""
        pass

    @abstractmethod
    def update_feedback(self, event_id: str, feedback: dict) -> None:
        """更新反馈，同时更新策略权重."""
        pass
```

- [ ] **Step 2: 创建 `app/memory/stores/__init__.py`**

```python
"""MemoryStore 实现模块."""

from app.memory.stores.base import BaseMemoryStore
from app.memory.stores.keyword_store import KeywordMemoryStore
from app.memory.stores.llm_store import LLMOnlyMemoryStore
from app.memory.stores.embedding_store import EmbeddingMemoryStore
from app.memory.stores.memory_bank_store import MemoryBankStore

__all__ = [
    "BaseMemoryStore",
    "KeywordMemoryStore",
    "LLMOnlyMemoryStore",
    "EmbeddingMemoryStore",
    "MemoryBankStore",
]
```

- [ ] **Step 3: 创建 `app/memory/stores/base.py`**

```python
"""MemoryStore 基类，提供共享的 events_store 和通用逻辑."""

from abc import ABC
from datetime import datetime
from app.memory.interfaces import MemoryStore
from app.storage.json_store import JSONStore


class BaseMemoryStore(MemoryStore, ABC):
    """MemoryStore 基类."""

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.events_store = JSONStore(data_dir, "events.json", list)
        self.strategies_store = JSONStore(data_dir, "strategies.json", dict)

    def get_history(self, limit: int = 10) -> list[dict]:
        events = self.events_store.read()
        if limit <= 0:
            return []
        return events[-limit:]

    def update_feedback(self, event_id: str, feedback: dict) -> None:
        feedback_store = JSONStore(self.data_dir, "feedback.json", list)
        feedback["event_id"] = event_id
        feedback["timestamp"] = datetime.now().isoformat()
        feedback_store.append(feedback)
        self._update_strategy(event_id, feedback)

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
```

- [ ] **Step 4: 提交**

```bash
git add app/memory/interfaces.py app/memory/stores/__init__.py app/memory/stores/base.py
git commit -m "feat(memory): add MemoryStore interface and BaseMemoryStore"
```

---

### 任务 2: 实现 KeywordMemoryStore

**Files:**
- Create: `app/memory/stores/keyword_store.py`
- Create: `tests/stores/__init__.py`
- Create: `tests/stores/test_keyword_store.py`

- [ ] **Step 1: 创建 `app/memory/stores/keyword_store.py`**

```python
"""关键词匹配检索 store."""

import uuid
from datetime import datetime
from app.memory.stores.base import BaseMemoryStore

_STORE_NAME = "keyword"


class KeywordMemoryStore(BaseMemoryStore):
    """关键词匹配检索 store."""

    @property
    def store_name(self) -> str:
        return _STORE_NAME

    def write(self, event: dict) -> str:
        event = dict(event)
        event_id = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
        event["id"] = event_id
        event["created_at"] = datetime.now().isoformat()
        self.events_store.append(event)
        return event_id

    def search(self, query: str) -> list[dict]:
        query_lower = query.lower()
        events = self.events_store.read()
        return [
            event
            for event in events
            if query_lower in event.get("content", "").lower()
            or query_lower in event.get("description", "").lower()
        ]
```

- [ ] **Step 2: 创建 `tests/stores/__init__.py`**

```python
"""Memory store tests."""
```

- [ ] **Step 3: 创建 `tests/stores/test_keyword_store.py`**

```python
"""Tests for KeywordMemoryStore."""

import pytest
from app.memory.stores.keyword_store import KeywordMemoryStore


@pytest.fixture
def store(tmp_path):
    return KeywordMemoryStore(str(tmp_path))


class TestKeywordMemoryStore:
    def test_write_returns_event_id(self, store):
        event_id = store.write({"content": "测试事件"})
        assert isinstance(event_id, str)

    def test_write_then_search_returns_event(self, store):
        event_id = store.write({"content": "测试事件"})
        results = store.search("测试")
        assert len(results) == 1
        assert results[0]["id"] == event_id

    def test_search_case_insensitive(self, store):
        store.write({"content": "Hello World"})
        results = store.search("hello")
        assert len(results) == 1

    def test_search_no_match(self, store):
        store.write({"content": "测试事件"})
        results = store.search("不存在")
        assert len(results) == 0

    def test_get_history_returns_recent_events(self, store):
        for i in range(5):
            store.write({"content": f"事件{i}"})
        history = store.get_history(limit=3)
        assert len(history) == 3

    def test_update_feedback_accept(self, store):
        event_id = store.write({"content": "事件"})
        store.update_feedback(event_id, {"action": "accept", "type": "meeting"})
        strategies = store.strategies_store.read()
        assert strategies["reminder_weights"]["meeting"] > 0.5

    def test_update_feedback_ignore(self, store):
        event_id = store.write({"content": "事件"})
        store.update_feedback(event_id, {"action": "ignore", "type": "meeting"})
        strategies = store.strategies_store.read()
        assert strategies["reminder_weights"]["meeting"] < 0.5
```

- [ ] **Step 4: 运行测试验证**

```bash
uv run pytest tests/stores/test_keyword_store.py -v
```

- [ ] **Step 5: 提交**

```bash
git add app/memory/stores/keyword_store.py tests/stores/
git commit -m "feat(memory): add KeywordMemoryStore"
```

---

### 任务 3: 实现 LLMOnlyMemoryStore

**Files:**
- Create: `app/memory/stores/llm_store.py`
- Create: `tests/stores/test_llm_store.py`

- [ ] **Step 1: 创建 `app/memory/stores/llm_store.py`**

```python
"""LLM 语义判断检索 store."""

import uuid
import json
import re
import logging
from datetime import datetime
from typing import Optional, TYPE_CHECKING

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
    """LLM 语义判断检索 store."""

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

    def write(self, event: dict) -> str:
        event = dict(event)
        event_id = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
        event["id"] = event_id
        event["created_at"] = datetime.now().isoformat()
        self.events_store.append(event)
        return event_id

    def search(self, query: str) -> list[dict]:
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
                        results.append(event)
            except Exception as e:
                logger.warning("LLM relevance check failed: %s", e, exc_info=True)
                continue

        return results
```

- [ ] **Step 2: 创建 `tests/stores/test_llm_store.py`**

```python
"""Tests for LLMOnlyMemoryStore."""

from unittest.mock import MagicMock

import pytest

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
        event_id = store.write({"content": "测试事件"})
        assert isinstance(event_id, str)

    def test_search_with_llm_returns_relevant(self, store):
        store.write({"content": "明天有会议"})
        results = store.search("有什么安排")
        assert len(results) == 1

    def test_search_without_llm_returns_empty(self, store_without_llm):
        store_without_llm.write({"content": "测试事件"})
        results = store_without_llm.search("测试")
        assert results == []

    def test_search_no_events_returns_empty(self, store):
        results = store.search("测试")
        assert results == []
```

- [ ] **Step 3: 运行测试验证**

```bash
uv run pytest tests/stores/test_llm_store.py -v
```

- [ ] **Step 4: 提交**

```bash
git add app/memory/stores/llm_store.py tests/stores/test_llm_store.py
git commit -m "feat(memory): add LLMOnlyMemoryStore"
```

---

### 任务 4: 实现 EmbeddingMemoryStore

**Files:**
- Create: `app/memory/stores/embedding_store.py`
- Create: `tests/stores/test_embedding_store.py`

- [ ] **Step 1: 创建 `app/memory/stores/embedding_store.py`**

```python
"""向量相似度检索 store."""

import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from app.memory.stores.base import BaseMemoryStore
from app.memory.utils import cosine_similarity

if TYPE_CHECKING:
    from app.models.embedding import EmbeddingModel


class EmbeddingMemoryStore(BaseMemoryStore):
    """向量相似度检索 store."""

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

    def write(self, event: dict) -> str:
        event = dict(event)
        event_id = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
        event["id"] = event_id
        event["created_at"] = datetime.now().isoformat()
        self.events_store.append(event)
        return event_id

    def search(self, query: str) -> list[dict]:
        if self.embedding_model is None:
            return self._keyword_fallback(query)

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
                results.append(event)

        return results

    def _keyword_fallback(self, query: str) -> list[dict]:
        query_lower = query.lower()
        events = self.events_store.read()
        return [
            event
            for event in events
            if query_lower in event.get("content", "").lower()
        ]
```

- [ ] **Step 2: 创建 `tests/stores/test_embedding_store.py`**

```python
"""Tests for EmbeddingMemoryStore."""

from unittest.mock import MagicMock

import pytest

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
        event_id = store.write({"content": "测试事件"})
        assert isinstance(event_id, str)

    def test_search_with_embedding(self, store):
        store.write({"content": "明天有会议"})
        results = store.search("有什么安排")
        assert len(results) == 1

    def test_search_without_embedding_falls_back_to_keyword(self, store_without_embedding):
        store_without_embedding.write({"content": "测试事件"})
        results = store_without_embedding.search("测试")
        assert len(results) == 1

    def test_search_no_events_returns_empty(self, store):
        results = store.search("测试")
        assert results == []
```

- [ ] **Step 3: 运行测试验证**

```bash
uv run pytest tests/stores/test_embedding_store.py -v
```

- [ ] **Step 4: 提交**

```bash
git add app/memory/stores/embedding_store.py tests/stores/test_embedding_store.py
git commit -m "feat(memory): add EmbeddingMemoryStore"
```

---

### 任务 5: 迁移 MemoryBankStore

**Files:**
- Create: `app/memory/stores/memory_bank_store.py`
- Create: `tests/stores/test_memory_bank_store.py`

- [ ] **Step 1: 读取现有 `memory_bank.py` 理解完整逻辑**

```bash
cat app/memory/memory_bank.py
```

- [ ] **Step 2: 创建 `app/memory/stores/memory_bank_store.py`**

```python
"""遗忘曲线 + 分层摘要 store."""

import math
import uuid
from datetime import date, datetime
from typing import Optional, TYPE_CHECKING

from app.memory.stores.base import BaseMemoryStore
from app.memory.utils import cosine_similarity

if TYPE_CHECKING:
    from app.models.embedding import EmbeddingModel
    from app.models.chat import ChatModel

from app.storage.json_store import JSONStore

AGGREGATION_SIMILARITY_THRESHOLD = 0.8
DAILY_SUMMARY_THRESHOLD = 5
OVERALL_SUMMARY_THRESHOLD = 3
SUMMARY_WEIGHT = 0.8
TOP_K = 3


def forgetting_curve(days_elapsed: int, strength: int) -> float:
    """根据艾宾浩斯遗忘曲线计算记忆保留率."""
    if days_elapsed <= 0:
        return 1.0
    return math.exp(-days_elapsed / (5 * strength))


class MemoryBankStore(BaseMemoryStore):
    """遗忘曲线 + 分层摘要 store."""

    def __init__(
        self,
        data_dir: str,
        embedding_model: Optional["EmbeddingModel"] = None,
        chat_model: Optional["ChatModel"] = None,
    ):
        super().__init__(data_dir)
        self.embedding_model = embedding_model
        self.chat_model = chat_model
        self.interactions_store = JSONStore(data_dir, "interactions.json", list)
        self._default_summaries = {"daily_summaries": {}, "overall_summary": ""}
        self.summaries_store = JSONStore(
            data_dir,
            "memorybank_summaries.json",
            lambda: dict(self._default_summaries),
        )

    @property
    def store_name(self) -> str:
        return "memorybank"

    def write(self, event: dict) -> str:
        """写入事件并触发可能的每日摘要生成."""
        event = dict(event)
        event_id = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
        today = date.today().isoformat()
        event["id"] = event_id
        event["created_at"] = datetime.now().isoformat()
        event["memory_strength"] = 1
        event["last_recall_date"] = today
        event["date_group"] = today
        self.events_store.append(event)
        self._maybe_summarize(today)
        return event_id

    def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str:
        """写入交互记录，自动聚合到已有事件或创建新事件."""
        interaction_id = (
            f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
        )
        today = date.today().isoformat()
        interaction = {
            "id": interaction_id,
            "event_id": "",
            "query": query,
            "response": response,
            "timestamp": datetime.now().isoformat(),
            "memory_strength": 1,
            "last_recall_date": today,
        }
        self.interactions_store.append(interaction)

        append_event_id = self._should_append_to_event(interaction)
        if append_event_id:
            interaction["event_id"] = append_event_id
            self._append_interaction_to_event(append_event_id, interaction_id)
            self._update_event_summary(append_event_id)
        else:
            event_id = (
                f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
            )
            now_iso = datetime.now().isoformat()
            event = {
                "id": event_id,
                "content": query,
                "type": event_type,
                "interaction_ids": [interaction_id],
                "created_at": now_iso,
                "updated_at": now_iso,
                "memory_strength": 1,
                "last_recall_date": today,
                "date_group": today,
            }
            self.events_store.append(event)
            interaction["event_id"] = event_id

        self._persist_interaction(interaction)
        self._maybe_summarize(today)
        return interaction_id

    def search(self, query: str, top_k: int = TOP_K) -> list[dict]:
        """根据查询检索相关事件和摘要."""
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
        all_results.sort(key=lambda x: x.get("_score", 0.0), reverse=True)
        top_results = all_results[:top_k]
        return self._expand_event_interactions(top_results)

    def _search_by_keyword(
        self, query: str, events: list[dict], top_k: int
    ) -> list[dict]:
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
                scored = dict(event)
                scored["_score"] = retention
                results.append(scored)
        results.sort(key=lambda x: x["_score"], reverse=True)
        top_results = results[:top_k]
        self._strengthen_events(top_results)
        return top_results

    def _search_by_embedding(
        self, query: str, events: list[dict], top_k: int
    ) -> list[dict]:
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
                scored = dict(event)
                scored["_score"] = score
                results.append(scored)
        results.sort(key=lambda x: x["_score"], reverse=True)
        top_results = results[:top_k]
        self._strengthen_events(top_results)
        return top_results

    def _expand_event_interactions(self, results: list[dict]) -> list[dict]:
        interactions = self.interactions_store.read()
        interaction_by_event: dict[str, list[dict]] = {}
        for i in interactions:
            eid = i.get("event_id", "")
            if eid:
                interaction_by_event.setdefault(eid, []).append(i)
        for result in results:
            eid = result.get("id", "")
            result["interactions"] = interaction_by_event.get(eid, [])
        return results

    def _strengthen_interactions(self, event_ids: set[str]) -> None:
        if not event_ids:
            return
        all_interactions = self.interactions_store.read()
        today = date.today().isoformat()
        updated = False
        for interaction in all_interactions:
            if interaction.get("event_id") in event_ids:
                interaction["memory_strength"] = (
                    interaction.get("memory_strength", 1) + 1
                )
                interaction["last_recall_date"] = today
                updated = True
        if updated:
            self.interactions_store.write(all_interactions)

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
        for event in matched_events:
            if "id" in event:
                event["memory_strength"] = event.get("memory_strength", 1) + 1
                event["last_recall_date"] = today
        self._strengthen_interactions(matched_ids)

    def _search_summaries(
        self, query: str, daily_summaries: dict, top_k: int = 1
    ) -> list[dict]:
        if not daily_summaries:
            return []
        query_lower = query.lower()
        today = date.today()
        results = []
        matched_keys = []
        for date_group, summary_data in daily_summaries.items():
            if isinstance(summary_data, dict):
                content = summary_data.get("content", "")
                strength = summary_data.get("memory_strength", 1)
                last_recall = summary_data.get("last_recall_date", date_group)
            else:
                content = str(summary_data)
                strength = 1
                last_recall = date_group
            if query_lower in content.lower():
                try:
                    last_date = date.fromisoformat(str(last_recall))
                    days_elapsed = (today - last_date).days
                except (ValueError, TypeError):
                    days_elapsed = 0
                retention = forgetting_curve(days_elapsed, strength)
                score = retention * SUMMARY_WEIGHT
                results.append(
                    {
                        "_source": "daily_summary",
                        "_score": score,
                        "content": content,
                        "date_group": date_group,
                        "memory_strength": strength,
                        "last_recall_date": last_recall,
                    }
                )
                matched_keys.append(date_group)
        results.sort(key=lambda x: x["_score"], reverse=True)
        self._strengthen_summaries(matched_keys, daily_summaries)
        return results[:top_k]

    def _strengthen_summaries(
        self, matched_keys: list[str], daily_summaries: dict
    ) -> None:
        if not matched_keys:
            return
        today = date.today().isoformat()
        updated = False
        for key in matched_keys:
            if key in daily_summaries:
                summary_data = daily_summaries[key]
                if isinstance(summary_data, dict):
                    summary_data["memory_strength"] = (
                        summary_data.get("memory_strength", 1) + 1
                    )
                    summary_data["last_recall_date"] = today
                    updated = True
        if updated:
            summaries = self.summaries_store.read()
            summaries["daily_summaries"] = daily_summaries
            self.summaries_store.write(summaries)

    def _should_append_to_event(self, interaction: dict) -> Optional[str]:
        events = self.events_store.read()
        if not events:
            return None
        today = date.today().isoformat()
        recent = events[-1]
        if recent.get("date_group") != today:
            return None
        if self.embedding_model:
            query_vec = self.embedding_model.encode(interaction["query"])
            event_vec = self.embedding_model.encode(recent.get("content", ""))
            similarity = cosine_similarity(query_vec, event_vec)
            if similarity >= AGGREGATION_SIMILARITY_THRESHOLD:
                return recent["id"]
            return None
        content_lower = recent.get("content", "").lower()
        query_lower = interaction["query"].lower()
        query_chars = list(set(query_lower))
        if not query_chars:
            return None
        overlap = sum(1 for c in query_chars if c in content_lower)
        if overlap / len(query_chars) >= 0.5:
            return recent["id"]
        return None

    def _append_interaction_to_event(self, event_id: str, interaction_id: str) -> None:
        all_events = self.events_store.read()
        for event in all_events:
            if event.get("id") == event_id:
                event.setdefault("interaction_ids", []).append(interaction_id)
                event["updated_at"] = datetime.now().isoformat()
                break
        self.events_store.write(all_events)

    def _update_event_summary(self, event_id: str) -> None:
        if not self.chat_model:
            return
        interactions = self.interactions_store.read()
        child_interactions = [i for i in interactions if i.get("event_id") == event_id]
        if not child_interactions:
            return
        combined = "\n".join(
            f"用户: {i['query']}\n系统: {i['response']}" for i in child_interactions
        )
        prompt = f"请简洁总结以下交互记录（一句话）：\n{combined}"
        try:
            summary_text = self.chat_model.generate(prompt)
        except Exception:
            return
        all_events = self.events_store.read()
        for event in all_events:
            if event.get("id") == event_id:
                event["content"] = summary_text
                break
        self.events_store.write(all_events)

    def _persist_interaction(self, interaction: dict) -> None:
        all_interactions = self.interactions_store.read()
        for i, item in enumerate(all_interactions):
            if item["id"] == interaction["id"]:
                all_interactions[i] = interaction
                break
        self.interactions_store.write(all_interactions)

    def _maybe_summarize(self, date_group: str) -> None:
        events = self.events_store.read()
        group_events = [e for e in events if e.get("date_group") == date_group]
        count = len(group_events)
        if count < DAILY_SUMMARY_THRESHOLD:
            return
        summaries = self.summaries_store.read()
        daily_summaries = summaries.get("daily_summaries", {})
        if date_group in daily_summaries:
            existing = daily_summaries[date_group]
            if isinstance(existing, dict) and existing.get("event_count", 0) >= count:
                return
        if not self.chat_model:
            return
        content = "\n".join(
            e.get("content", "") for e in group_events if e.get("content")
        )
        prompt = f"请简洁总结以下事件（一句话）：\n{content}"
        try:
            summary_text = self.chat_model.generate(prompt)
        except Exception:
            return
        daily_summaries[date_group] = {
            "content": summary_text,
            "memory_strength": 1,
            "last_recall_date": date_group,
            "event_count": count,
        }
        summaries["daily_summaries"] = daily_summaries
        self.summaries_store.write(summaries)
        if len(daily_summaries) >= OVERALL_SUMMARY_THRESHOLD:
            self._update_overall_summary(daily_summaries, summaries)

    def _update_overall_summary(self, daily_summaries: dict, summaries: dict) -> None:
        if not self.chat_model:
            return
        all_summaries = []
        for date_group, summary_data in daily_summaries.items():
            if isinstance(summary_data, dict):
                all_summaries.append(
                    f"[{date_group}] {summary_data.get('content', '')}"
                )
            else:
                all_summaries.append(f"[{date_group}] {summary_data}")
        combined = "\n".join(all_summaries)
        prompt = f"请简洁总结以下每日摘要（两到三句话）：\n{combined}"
        try:
            overall = self.chat_model.generate(prompt)
        except Exception:
            return
        summaries["overall_summary"] = overall
        self.summaries_store.write(summaries)
```

- [ ] **Step 3: 创建 `tests/stores/test_memory_bank_store.py`**

```python
"""Tests for MemoryBankStore."""

from unittest.mock import MagicMock

import pytest

from app.memory.stores.memory_bank_store import (
    DAILY_SUMMARY_THRESHOLD,
    MemoryBankStore,
)


@pytest.fixture
def mock_chat_model():
    chat = MagicMock()
    chat.generate.return_value = "测试摘要"
    return chat


@pytest.fixture
def store(tmp_path):
    return MemoryBankStore(str(tmp_path))


@pytest.fixture
def store_with_llm(tmp_path, mock_chat_model):
    return MemoryBankStore(str(tmp_path), chat_model=mock_chat_model)


class TestSearchWithForgetting:
    def test_search_no_embedding_returns_keyword(self, store):
        store.write({"content": "今天天气很好"})
        results = store.search("天气")
        assert len(results) > 0
        assert "天气" in results[0]["content"]

    def test_search_empty_events(self, store):
        assert store.search("测试") == []

    def test_search_returns_top_k(self, store):
        for i in range(10):
            store.write({"content": f"事件{i}关于天气"})
        results = store.search("天气")
        assert len(results) <= 3


class TestRecallStrengthening:
    def test_search_increases_memory_strength(self, store):
        store.write({"content": "重要的会议"})
        store.search("会议")
        events = store.events_store.read()
        assert events[0]["memory_strength"] == 2

    def test_search_updates_only_matched_events(self, store):
        store.write({"content": "关于天气的事件"})
        store.write({"content": "关于会议的事件"})
        store.search("天气")
        events = store.events_store.read()
        weather = [e for e in events if "天气" in e["content"]][0]
        meeting = [e for e in events if "会议" in e["content"]][0]
        assert weather["memory_strength"] == 2
        assert meeting["memory_strength"] == 1


class TestHierarchicalSummarization:
    def test_summarize_trigger_threshold(self, tmp_path, mock_chat_model):
        backend = MemoryBankStore(str(tmp_path), chat_model=mock_chat_model)
        for i in range(DAILY_SUMMARY_THRESHOLD):
            backend.write({"content": f"事件{i}"})
        summaries = backend.summaries_store.read()
        today = backend.events_store.read()[0]["date_group"]
        assert today in summaries["daily_summaries"]
        assert mock_chat_model.generate.called

    def test_no_summary_below_threshold(self, tmp_path, mock_chat_model):
        backend = MemoryBankStore(str(tmp_path), chat_model=mock_chat_model)
        for i in range(DAILY_SUMMARY_THRESHOLD - 1):
            backend.write({"content": f"事件{i}"})
        summaries = backend.summaries_store.read()
        assert len(summaries["daily_summaries"]) == 0


class TestWriteInteraction:
    def test_write_interaction_creates_record(self, store):
        interaction_id = store.write_interaction("提醒我开会", "好的")
        assert isinstance(interaction_id, str)
        interactions = store.interactions_store.read()
        assert interactions[0]["id"] == interaction_id

    def test_write_interaction_aggregates_similar(self, store):
        store.write_interaction("提醒我明天上午开会", "好的")
        store.write_interaction("明天下午也有会议", "已更新")
        events = store.events_store.read()
        assert len(events) == 1
        assert len(events[0]["interaction_ids"]) == 2
```

- [ ] **Step 4: 运行测试验证**

```bash
uv run pytest tests/stores/test_memory_bank_store.py -v
```

- [ ] **Step 5: 提交**

```bash
git add app/memory/stores/memory_bank_store.py tests/stores/test_memory_bank_store.py
git commit -m "feat(memory): add MemoryBankStore"
```

---

### 任务 6: 重构 MemoryModule 为 Facade

**Files:**
- Modify: `app/memory/__init__.py`
- Create: `app/memory/memory.py` (覆盖)
- Delete: `app/memory/memory_bank.py`

- [ ] **Step 1: 创建 `app/memory/memory.py`**

```python
"""统一记忆管理接口，Facade 模式 + 工厂注册表."""

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.chat import ChatModel
    from app.models.embedding import EmbeddingModel

_STORES_REGISTRY: dict[str, type] = {}


def register_store(name: str, store_cls: type) -> None:
    """注册 MemoryStore 实现类，用于工厂创建."""
    _STORES_REGISTRY[name] = store_cls


def _import_all_stores() -> None:
    """延迟导入所有 store 类并注册到工厂注册表."""
    from app.memory.stores.keyword_store import KeywordMemoryStore
    from app.memory.stores.llm_store import LLMOnlyMemoryStore
    from app.memory.stores.embedding_store import EmbeddingMemoryStore
    from app.memory.stores.memory_bank_store import MemoryBankStore

    register_store("keyword", KeywordMemoryStore)
    register_store("llm_only", LLMOnlyMemoryStore)
    register_store("embeddings", EmbeddingMemoryStore)
    register_store("memorybank", MemoryBankStore)


class MemoryModule:
    """统一记忆管理接口，Facade 模式."""

    def __init__(
        self,
        data_dir: str,
        embedding_model: Optional["EmbeddingModel"] = None,
        chat_model: Optional["ChatModel"] = None,
    ):
        _import_all_stores()
        self._stores: dict[str, any] = {}
        self._data_dir = data_dir
        self._embedding_model = embedding_model
        self._chat_model = chat_model
        self._default_mode: str = "memorybank"

    def _get_store(self, mode: str):
        """懒加载获取指定模式的 store."""
        if mode not in self._stores:
            self._stores[mode] = self._create_store(mode)
        return self._stores[mode]

    def _create_store(self, mode: str):
        """工厂方法创建 store，优先使用注册表."""
        if mode in _STORES_REGISTRY:
            store_cls = _STORES_REGISTRY[mode]
            return store_cls(self._data_dir, self._embedding_model, self._chat_model)

        raise ValueError(f"Unknown mode: {mode}. Available: {list(_STORES_REGISTRY.keys())}")

    def set_default_mode(self, mode: str) -> None:
        """设置默认模式."""
        if mode not in _STORES_REGISTRY:
            raise ValueError(f"Unknown mode: {mode}")
        self._default_mode = mode

    def write(self, event: dict) -> str:
        """写入事件到当前模式的 store."""
        store = self._get_store(self._default_mode)
        return store.write(event)

    def write_interaction(self, query: str, response: str, event_type: str = "reminder") -> str:
        """写入交互记录，仅 MemoryBankStore 支持."""
        store = self._get_store(self._default_mode)
        if not hasattr(store, "write_interaction"):
            raise NotImplementedError(
                f"write_interaction not supported for mode {self._default_mode}"
            )
        return store.write_interaction(query, response, event_type)

    def search(self, query: str, mode: str | None = None) -> list:
        """检索记忆."""
        target_mode = mode or self._default_mode
        return self._get_store(target_mode).search(query)

    def get_history(self, limit: int = 10) -> list:
        """获取历史记录."""
        return self._get_store(self._default_mode).get_history(limit)

    def update_feedback(self, event_id: str, feedback: dict) -> None:
        """更新反馈."""
        self._get_store(self._default_mode).update_feedback(event_id, feedback)
```

- [ ] **Step 2: 更新 `app/memory/__init__.py`**

```python
"""Memory module exports."""

from app.memory.memory import MemoryModule, register_store

__all__ = ["MemoryModule", "register_store"]
```

- [ ] **Step 3: 创建 Facade 测试**

```python
# tests/test_memory_module_facade.py

import pytest
from app.memory.memory import MemoryModule


@pytest.fixture
def mm(tmp_path):
    return MemoryModule(str(tmp_path))


class TestMemoryModuleFacade:
    def test_default_mode_is_memorybank(self, mm):
        assert mm._default_mode == "memorybank"

    def test_write_uses_default_mode(self, mm):
        mm.write({"content": "事件"})
        history = mm.get_history()
        assert len(history) == 1

    def test_search_routes_to_correct_store(self, mm):
        mm.write({"content": "测试事件"})
        results = mm.search("测试", mode="keyword")
        assert len(results) == 1

    def test_set_default_mode(self, mm):
        mm.set_default_mode("keyword")
        assert mm._default_mode == "keyword"

    def test_write_interaction_calls_memorybank(self, mm):
        interaction_id = mm.write_interaction("提醒我开会", "好的")
        assert isinstance(interaction_id, str)

    def test_write_interaction_raises_for_non_memorybank(self, mm):
        mm.set_default_mode("keyword")
        with pytest.raises(NotImplementedError):
            mm.write_interaction("q", "r")
```

- [ ] **Step 4: 运行测试验证**

```bash
uv run pytest tests/test_memory_module_facade.py -v
```

- [ ] **Step 5: 删除旧文件**

```bash
rm app/memory/memory_bank.py
```

- [ ] **Step 6: 提交**

```bash
git add app/memory/memory.py app/memory/__init__.py
git rm app/memory/memory_bank.py
git commit -m "refactor(memory): convert MemoryModule to Facade with store registry"
```

---

### 任务 7: 接口契约测试

**Files:**
- Create: `tests/test_memory_store_contract.py`

- [ ] **Step 1: 创建契约测试**

```python
"""MemoryStore 接口契约测试 - 验证所有实现满足统一接口."""

import pytest


class TestMemoryStoreContract:
    """验证所有 MemoryStore 实现满足接口契约."""

    @pytest.fixture(params=["keyword", "llm_only", "embeddings", "memorybank"])
    def store(self, request, tmp_path):
        # Note: 使用 _get_store() 访问内部实现是契约测试的设计决策
        # 因为需要验证每个 store 实现都满足同一接口
        from app.memory.memory import MemoryModule
        mm = MemoryModule(str(tmp_path))
        return mm._get_store(request.param)

    def test_write_returns_string_id(self, store):
        event_id = store.write({"content": "test"})
        assert isinstance(event_id, str)
        assert len(event_id) > 0

    def test_write_then_search_returns_same_event(self, store):
        event_id = store.write({"content": "测试事件"})
        events = store.events_store.read()
        assert any(e["id"] == event_id for e in events)

    def test_search_returns_list(self, store):
        store.write({"content": "测试事件"})
        results = store.search("测试")
        assert isinstance(results, list)

    def test_get_history_returns_list(self, store):
        store.write({"content": "事件1"})
        history = store.get_history(limit=10)
        assert isinstance(history, list)

    def test_get_history_respects_limit(self, store):
        for i in range(5):
            store.write({"content": f"事件{i}"})
        history = store.get_history(limit=3)
        assert len(history) == 3

    def test_update_feedback_updates_strategies(self, store):
        event_id = store.write({"content": "事件"})
        store.update_feedback(event_id, {"action": "accept", "type": "meeting"})
        strategies = store.strategies_store.read()
        assert "reminder_weights" in strategies
```

- [ ] **Step 2: 运行测试验证**

```bash
uv run pytest tests/test_memory_store_contract.py -v
```

- [ ] **Step 3: 提交**

```bash
git add tests/test_memory_store_contract.py
git commit -m "test(memory): add MemoryStore interface contract tests"
```

---

### 任务 8: 迁移遗留测试并清理

**Files:**
- Modify: `tests/test_memory_bank.py` (移动到 stores)
- Run: `uv run pytest tests/ -v`

- [ ] **Step 1: 验证所有测试通过**

```bash
uv run pytest tests/ -v
```
**如果测试失败**: 修复失败后再继续，不要跳过任何失败测试。

- [ ] **Step 2: 检查是否有遗漏的旧代码引用**

```bash
ruff check app/memory/
```
**如果 ruff 报错**: 修复代码问题后再继续。

- [ ] **Step 3: 最终提交**

```bash
git add -A
git commit -m "test(memory): migrate legacy tests and finalize refactoring"
```

---

## 依赖关系

```
任务1 (接口层)
    ↓
任务2,3,4,5 (四种Store实现) - 可并行
    ↓
任务6 (MemoryModule Facade)
    ↓
任务7 (契约测试)
    ↓
任务8 (测试迁移)
```

## 风险缓解

| 风险 | 缓解 |
|------|------|
| 旧代码引用断裂 | 任务8 检查 ruff 错误 |
| 原有测试失败 | 任务8 运行全部测试 |
| 注册顺序问题 | `_import_all_stores()` 延迟导入 |
