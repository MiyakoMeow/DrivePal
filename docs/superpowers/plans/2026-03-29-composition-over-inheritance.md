# 组合大于继承 重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将项目中所有基于继承的类型定义重构为基于组合的设计。

**Architecture:** 三个独立子系统按依赖顺序重构：(1) Provider 配置层提取共享 ProviderConfig；(2) MemoryStore 层拆分 BaseMemoryStore 为可组合组件 + Protocol；(3) Loader 层改为注册表 + Protocol。每层完成后全量测试验证。

**Tech Stack:** Python 3.13, Pydantic, pytest, ruff

**Spec:** `docs/superpowers/specs/2026-03-29-composition-over-inheritance-design.md`

---

## File Structure

### 新建文件
- `app/memory/components.py` — 5 个可组合组件（EventStorage, KeywordSearch, FeedbackManager, SimpleInteractionWriter, MemoryBankEngine）
- `app/experiment/loaders/base.py` — DatasetLoader Protocol

### 删除文件
- `app/memory/stores/base.py` — BaseMemoryStore 基类，逻辑拆入 components.py

### 修改文件
- `app/models/settings.py` — ProviderConfig 提取 + 各 *Config 改为组合
- `app/models/chat.py` — provider.* → provider.provider.*
- `app/models/embedding.py` — 同上 + fallback 构造适配
- `app/memory/interfaces.py` — ABC → Protocol
- `app/memory/memory.py` — 注册表类型适配
- `app/memory/stores/__init__.py` — 移除 BaseMemoryStore 导出
- `app/memory/stores/keyword_store.py` — 重写为组合
- `app/memory/stores/llm_store.py` — 重写为组合
- `app/memory/stores/embedding_store.py` — 重写为组合
- `app/memory/stores/memory_bank_store.py` — 重写为组合
- `app/experiment/loaders/__init__.py` — 注册表 + get_test_cases()
- `app/experiment/loaders/sgd_calendar.py` — @classmethod → 实例方法
- `app/experiment/loaders/scheduler.py` — @classmethod → 实例方法
- `app/experiment/runners/prepare.py` — _load_dataset 改用 loaders.get_test_cases()
- `app/experiment/runners/judge.py` — provider.model → provider.provider.model
- `tests/conftest.py` — provider.* → provider.provider.*
- `tests/test_settings.py` — 全面适配新 ProviderConfig 结构
- `tests/test_memory_store_contract.py` — 属性代理适配
- `tests/test_memory_bank.py` — 属性代理适配
- `tests/stores/test_keyword_store.py` — 属性代理适配
- `tests/stores/test_memory_bank_store.py` — 属性代理适配
- `tests/test_judge.py` — provider.model → provider.provider.model + mock 构造适配
- `tests/test_prepare.py` — patch 路径更新

---

**任务依赖关系：**
- Task 1（Provider 层）→ 无依赖，可独立执行
- Task 2（组件提取）→ 无依赖，可独立执行
- Task 3（Store 重写）→ 依赖 Task 2
- Task 4（测试适配）→ 依赖 Task 3
- Task 5（Loader 层）→ 无依赖，可独立执行
- Task 6（最终验证）→ 依赖所有前置任务

Task 1、Task 2、Task 5 三者可并行执行。

---

## Task 1: Provider 配置层重构（独立）

**Files:**
- Modify: `app/models/settings.py`
- Modify: `app/models/chat.py`
- Modify: `app/models/embedding.py`
- Modify: `tests/conftest.py`
- Modify: `tests/test_judge.py`

- [ ] **Step 1: 重写 settings.py 中的配置 dataclass**

将 `LLMProviderConfig`、`EmbeddingProviderConfig`、`JudgeProviderConfig` 改为组合 `ProviderConfig`：

```python
@dataclass
class ProviderConfig:
    model: str
    base_url: str | None = None
    api_key: str | None = None

@dataclass
class LLMProviderConfig:
    provider: ProviderConfig
    temperature: float = 0.7

    @classmethod
    def from_dict(cls, d: dict) -> "LLMProviderConfig":
        return cls(
            provider=ProviderConfig(
                model=d["model"],
                base_url=d.get("base_url"),
                api_key=d.get("api_key"),
            ),
            temperature=d.get("temperature", 0.7),
        )

@dataclass
class EmbeddingProviderConfig:
    provider: ProviderConfig
    device: str = "cpu"

    @classmethod
    def from_dict(cls, d: dict) -> "EmbeddingProviderConfig":
        return cls(
            provider=ProviderConfig(
                model=d["model"],
                base_url=d.get("base_url"),
                api_key=d.get("api_key"),
            ),
            device=d.get("device", "cpu"),
        )

@dataclass
class JudgeProviderConfig:
    provider: ProviderConfig
    temperature: float = 0.1

    @classmethod
    def from_dict(cls, d: dict) -> "JudgeProviderConfig":
        return cls(
            provider=ProviderConfig(
                model=d["model"],
                base_url=d.get("base_url"),
                api_key=d.get("api_key"),
            ),
            temperature=d.get("temperature", 0.1),
        )
```

同时修改：
- `_build_env_provider()`: 构造 `LLMProviderConfig(provider=ProviderConfig(...))`
- `_build_judge_provider()`: 构造 `JudgeProviderConfig(provider=ProviderConfig(...))`
- `LLMSettings.load()` 去重 key: `(p.model, p.base_url)` → `(p.provider.model, p.provider.base_url)`
- `get_judge_model()`: 从 judge_setting 构造 `LLMProviderConfig(provider=ProviderConfig(model=..., base_url=..., api_key=...), temperature=...)`

- [ ] **Step 2: 修改 chat.py 适配嵌套访问**

所有 `provider.model` → `provider.provider.model`
所有 `provider.base_url` → `provider.provider.base_url`
所有 `provider.api_key` → `provider.provider.api_key`
所有 `provider.temperature` 保留在 `provider.temperature`

- [ ] **Step 3: 修改 embedding.py 适配嵌套访问**

同 chat.py，另加 fallback 构造适配：
```python
# EmbeddingModel.__init__ fallback
providers = [
    EmbeddingProviderConfig(
        provider=ProviderConfig(model="BAAI/bge-small-zh-v1.5"),
        device=device or "cpu",
    )
]
```

`_create_client` 中 `provider.model` → `provider.provider.model`，`provider.base_url` → `provider.provider.base_url`，`provider.api_key` → `provider.provider.api_key`，`provider.device` 保留在 `provider.device`。

- [ ] **Step 4: 修改 conftest.py**

`provider.base_url` → `provider.provider.base_url`
`provider.api_key` → `provider.provider.api_key`
添加 `from app.models.settings import ProviderConfig`（如果构造 provider 需要）

- [ ] **Step 5: 修改 judge.py**

`judge_model.providers[0].model` → `judge_model.providers[0].provider.model`

- [ ] **Step 6: 修改 test_judge.py**

所有 mock 构造 `LLMProviderConfig` 改为嵌套结构。具体：
- `_make_mock_judge_model` 中 `model.providers = [MagicMock(model="deepseek-chat")]` 改为 `model.providers = [MagicMock(provider=MagicMock(model="deepseek-chat"))]`

- [ ] **Step 7: 修改 test_settings.py**

添加 `from app.models.settings import ProviderConfig` 导入。全面适配新的嵌套结构。所有 `LLMProviderConfig(model=..., base_url=..., api_key=..., temperature=...)` 改为 `LLMProviderConfig(provider=ProviderConfig(model=..., base_url=..., api_key=...), temperature=...)`。所有 `p.model` → `p.provider.model`，`p.base_url` → `p.provider.base_url`，`p.api_key` → `p.provider.api_key`。

- [ ] **Step 8: 运行 Provider 层相关测试**

Run: `uv run pytest tests/test_settings.py -v`
Expected: ALL PASS

- [ ] **Step 9: 运行全量测试确认无破坏**

Run: `uv run pytest tests/ -v --timeout=60`
Expected: ALL PASS

- [ ] **Step 10: Lint 检查**

Run: `uv run ruff check app/models/ tests/conftest.py tests/test_settings.py tests/test_judge.py app/experiment/runners/judge.py --fix`
Expected: 无错误

- [ ] **Step 11: Commit**

```bash
git add app/models/settings.py app/models/chat.py app/models/embedding.py tests/conftest.py tests/test_settings.py tests/test_judge.py app/experiment/runners/judge.py
git commit -m "refactor: extract ProviderConfig, compose into specialized configs"
```

---

## Task 2: MemoryStore 可组合组件提取（独立）

**Files:**
- Create: `app/memory/components.py`
- Modify: `app/memory/interfaces.py`

- [ ] **Step 1: 重写 interfaces.py — ABC → Protocol**

```python
"""MemoryStore 结构化接口定义（Protocol）."""

from typing import Protocol

from app.memory.schemas import FeedbackData, MemoryEvent, SearchResult


class MemoryStore(Protocol):
    """记忆存储接口，通过结构化子类型隐式满足."""

    store_name: str
    requires_embedding: bool
    requires_chat: bool
    supports_interaction: bool

    def write(self, event: MemoryEvent) -> str: ...
    def search(self, query: str, top_k: int = 10) -> list[SearchResult]: ...
    def get_history(self, limit: int = 10) -> list[MemoryEvent]: ...
    def update_feedback(self, event_id: str, feedback: FeedbackData) -> None: ...
    def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str: ...
```

- [ ] **Step 2: 创建 components.py — EventStorage**

从 `BaseMemoryStore.__init__`、`_generate_id`、`write` 中提取：

```python
"""MemoryStore 可组合组件."""

import uuid
from datetime import datetime

from app.memory.schemas import FeedbackData, MemoryEvent, SearchResult
from app.storage.json_store import JSONStore


class EventStorage:
    """事件 JSON 文件 CRUD + ID 生成."""

    def __init__(self, data_dir: str) -> None:
        self._store = JSONStore(data_dir, "events.json", list)
        self.data_dir = data_dir

    def generate_id(self) -> str:
        return f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

    def read_events(self) -> list[dict]:
        return self._store.read()

    def write_events(self, events: list[dict]) -> None:
        self._store.write(events)

    def append_event(self, event: MemoryEvent) -> str:
        event = event.model_copy(deep=True)
        event.id = self.generate_id()
        event.created_at = datetime.now().isoformat()
        self._store.append(event.model_dump())
        return event.id
```

- [ ] **Step 3: 向 components.py 添加 KeywordSearch**

从 `BaseMemoryStore._keyword_search` 提取：

```python
class KeywordSearch:
    """关键词大小写不敏感搜索."""

    def search(self, query: str, events: list[dict], top_k: int = 10) -> list[SearchResult]:
        query_lower = query.lower()
        matched = [
            e
            for e in events
            if query_lower in e.get("content", "").lower()
            or query_lower in e.get("description", "").lower()
        ]
        return [SearchResult(event=e) for e in matched[:top_k]]
```

- [ ] **Step 4: 向 components.py 添加 FeedbackManager**

从 `BaseMemoryStore.update_feedback`、`_update_strategy` 提取：

```python
class FeedbackManager:
    """反馈更新 + 策略权重管理."""

    def __init__(self, data_dir: str) -> None:
        self._strategies_store = JSONStore(data_dir, "strategies.json", dict)
        self.data_dir = data_dir

    def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        from datetime import datetime

        feedback.event_id = event_id
        feedback.timestamp = datetime.now().isoformat()
        feedback_store = JSONStore(self.data_dir, "feedback.json", list)
        feedback_store.append(feedback.model_dump())
        self._update_strategy(event_id, feedback.model_dump())

    def _update_strategy(self, event_id: str, feedback: dict) -> None:
        strategies = self._strategies_store.read()
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

        self._strategies_store.write(strategies)
```

- [ ] **Step 5: 向 components.py 添加 SimpleInteractionWriter**

从 `BaseMemoryStore.write_interaction` 提取：

```python
class SimpleInteractionWriter:
    """简单交互写入（创建 MemoryEvent 写入 EventStorage）."""

    def __init__(self, storage: EventStorage) -> None:
        self._storage = storage

    def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str:
        event = MemoryEvent(
            content=query,
            type=event_type,
            description=response,
        )
        return self._storage.append_event(event)
```

- [ ] **Step 6: 向 components.py 添加 MemoryBankEngine — 构造+write+search**

从 `MemoryBankStore` 提取。将原 `memory_bank_store.py` 的全部逻辑搬到此类，使用 `self._storage` 代替 `self.events_store`：

```python
import math
import uuid
from datetime import date, datetime
from typing import Optional

from app.memory.schemas import MemoryEvent, SearchResult
from app.memory.utils import cosine_similarity
from app.storage.json_store import JSONStore

AGGREGATION_SIMILARITY_THRESHOLD = 0.8
DAILY_SUMMARY_THRESHOLD = 2
OVERALL_SUMMARY_THRESHOLD = 3
SUMMARY_WEIGHT = 0.8
TOP_K = 3


def forgetting_curve(days_elapsed: int, strength: int) -> float:
    if days_elapsed <= 0:
        return 1.0
    return math.exp(-days_elapsed / (5 * strength))


class MemoryBankEngine:
    EMBEDDING_MIN_SIMILARITY = 0.3

    def __init__(self, data_dir, storage, embedding_model=None, chat_model=None):
        self._storage = storage
        self.data_dir = data_dir
        self.embedding_model = embedding_model
        self.chat_model = chat_model
        self._interactions_store = JSONStore(data_dir, "interactions.json", list)
        self._default_summaries = {"daily_summaries": {}, "overall_summary": ""}
        self._summaries_store = JSONStore(
            data_dir, "memorybank_summaries.json",
            lambda: dict(self._default_summaries),
        )

    def write(self, event: MemoryEvent) -> str:
        event = event.model_copy(deep=True)
        event.id = self._storage.generate_id()
        event.created_at = datetime.now().isoformat()
        today = date.today().isoformat()
        event.memory_strength = 1
        event.last_recall_date = today
        event.date_group = today
        self._storage._store.append(event.model_dump())
        self._maybe_summarize(today)
        return event.id

    def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        if not query.strip():
            return []
        events = self._storage.read_events()
        summaries = self._summaries_store.read()
        daily_summaries = summaries.get("daily_summaries", {})
        if not events and not daily_summaries:
            return []
        if self.embedding_model is None:
            event_results = self._search_by_keyword(query, events, top_k)
        else:
            event_results = self._search_by_embedding(query, events, top_k)
            if not event_results:
                event_results = self._search_by_keyword(query, events, top_k)
        summary_results = self._search_summaries(query, daily_summaries, top_k=1)
        all_results = event_results + summary_results
        all_results.sort(key=lambda x: x.score, reverse=True)
        top_results = all_results[:top_k]
        return self._expand_event_interactions(top_results)
```

- [ ] **Step 7: 向 MemoryBankEngine 添加 _search_by_keyword + _search_by_embedding**

从原 `MemoryBankStore._search_by_keyword` 和 `_search_by_embedding` 搬入。将 `self.events_store` → `self._storage._store`（读取时用 `self._storage.read_events()`），`self.events_store.write(all_events)` → `self._storage.write_events(all_events)`。

- [ ] **Step 8: 向 MemoryBankEngine 添加 _expand + _strengthen 系列**

从原 `_expand_event_interactions`、`_strengthen_events`、`_strengthen_interactions`、`_strengthen_summaries` 搬入。同样替换 `self.events_store` → `self._storage._store`，`self.interactions_store` → `self._interactions_store`。

- [ ] **Step 9: 向 MemoryBankEngine 添加 write_interaction + 聚合+摘要系列**

从原 `write_interaction`、`_should_append_to_event`、`_append_interaction_to_event`、`_update_event_summary`、`_persist_interaction`、`_maybe_summarize`、`_update_overall_summary` 搬入。同样替换底层存储访问。

- [ ] **Step 10: Commit**

```bash
git add app/memory/components.py app/memory/interfaces.py
git commit -m "refactor: extract composable components and MemoryStore Protocol"
```

---

## Task 3: 重写四个 Store 为组合

**Files:**
- Modify: `app/memory/stores/keyword_store.py`
- Modify: `app/memory/stores/llm_store.py`
- Modify: `app/memory/stores/embedding_store.py`
- Modify: `app/memory/stores/memory_bank_store.py`
- Modify: `app/memory/stores/__init__.py`
- Modify: `app/memory/memory.py`

- [ ] **Step 1: 重写 keyword_store.py**

```python
"""关键词匹配检索 store."""

from app.memory.components import (
    EventStorage,
    FeedbackManager,
    KeywordSearch,
    SimpleInteractionWriter,
)
from app.memory.schemas import FeedbackData, MemoryEvent, SearchResult
from app.storage.json_store import JSONStore


class KeywordMemoryStore:
    """关键词匹配检索 store."""

    store_name = "keyword"
    requires_embedding = False
    requires_chat = False
    supports_interaction = False

    def __init__(self, data_dir: str, **kwargs) -> None:
        self._storage = EventStorage(data_dir)
        self._search = KeywordSearch()
        self._feedback = FeedbackManager(data_dir)
        self._interaction = SimpleInteractionWriter(self._storage)

    @property
    def events_store(self) -> JSONStore:
        return self._storage._store

    @property
    def strategies_store(self) -> JSONStore:
        return self._feedback._strategies_store

    def write(self, event: MemoryEvent) -> str:
        return self._storage.append_event(event)

    def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        events = self._storage.read_events()
        return self._search.search(query, events, top_k)

    def get_history(self, limit: int = 10) -> list[MemoryEvent]:
        events = self._storage.read_events()
        if limit <= 0:
            return []
        return [MemoryEvent(**e) for e in events[-limit:]]

    def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        self._feedback.update_feedback(event_id, feedback)

    def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str:
        return self._interaction.write_interaction(query, response, event_type)
```

- [ ] **Step 2: 重写 llm_store.py**

```python
"""LLM 语义判断检索 store."""

import json
import logging
import re
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from app.memory.components import (
    EventStorage,
    FeedbackManager,
    SimpleInteractionWriter,
)
from app.memory.schemas import FeedbackData, MemoryEvent, SearchResult
from app.storage.json_store import JSONStore

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


class LLMOnlyMemoryStore:
    """LLM 语义判断检索 store."""

    store_name = "llm_only"
    requires_embedding = False
    requires_chat = True
    supports_interaction = False

    def __init__(self, data_dir: str, embedding_model=None, chat_model: Optional["ChatModel"] = None) -> None:
        self._storage = EventStorage(data_dir)
        self._feedback = FeedbackManager(data_dir)
        self._interaction = SimpleInteractionWriter(self._storage)
        self.chat_model = chat_model

    @property
    def events_store(self) -> JSONStore:
        return self._storage._store

    @property
    def strategies_store(self) -> JSONStore:
        return self._feedback._strategies_store

    def write(self, event: MemoryEvent) -> str:
        return self._storage.append_event(event)

    def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        if not self.chat_model:
            return []
        events = self._storage.read_events()
        if not events:
            return []
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        results = []
        for event in events:
            event_text = event.get("content", "") or event.get("description", "")
            prompt = f"当前时间：{now}\n\n" + LLM_SEARCH_PROMPT.format(
                query=query, event_description=event_text
            )
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

    def get_history(self, limit: int = 10) -> list[MemoryEvent]:
        events = self._storage.read_events()
        if limit <= 0:
            return []
        return [MemoryEvent(**e) for e in events[-limit:]]

    def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        self._feedback.update_feedback(event_id, feedback)

    def write_interaction(self, query: str, response: str, event_type: str = "reminder") -> str:
        return self._interaction.write_interaction(query, response, event_type)
```

- [ ] **Step 3: 重写 embedding_store.py**

```python
"""向量相似度检索 store."""

from typing import Optional, TYPE_CHECKING

from app.memory.components import (
    EventStorage,
    FeedbackManager,
    KeywordSearch,
    SimpleInteractionWriter,
)
from app.memory.schemas import FeedbackData, MemoryEvent, SearchResult
from app.memory.utils import cosine_similarity
from app.storage.json_store import JSONStore

if TYPE_CHECKING:
    from app.models.embedding import EmbeddingModel


class EmbeddingMemoryStore:
    """向量相似度检索 store."""

    store_name = "embeddings"
    requires_embedding = True
    requires_chat = False
    supports_interaction = False

    SIMILARITY_THRESHOLD = 0.4

    def __init__(self, data_dir: str, embedding_model: Optional["EmbeddingModel"] = None, chat_model=None) -> None:
        self._storage = EventStorage(data_dir)
        self._feedback = FeedbackManager(data_dir)
        self._interaction = SimpleInteractionWriter(self._storage)
        self._keyword_search = KeywordSearch()
        self.embedding_model = embedding_model

    @property
    def events_store(self) -> JSONStore:
        return self._storage._store

    @property
    def strategies_store(self) -> JSONStore:
        return self._feedback._strategies_store

    def write(self, event: MemoryEvent) -> str:
        return self._storage.append_event(event)

    def search(self, query: str, top_k: int = 10, min_results: int = 1) -> list[SearchResult]:
        events = self._storage.read_events()
        if not events:
            return []
        results = []
        if self.embedding_model:
            query_vector = self.embedding_model.encode(query)
            event_texts = [event.get("content", "") for event in events]
            all_embeddings = self.embedding_model.batch_encode(event_texts)
            seen_ids = set()
            scored = []
            for event, emb in zip(events, all_embeddings):
                sim = cosine_similarity(query_vector, emb)
                if sim > self.SIMILARITY_THRESHOLD:
                    scored.append((sim, event))
            scored.sort(key=lambda x: x[0], reverse=True)
            for sim, event in scored[:top_k]:
                seen_ids.add(event.get("id", ""))
                results.append(SearchResult(event=dict(event), score=sim))
            if len(results) < min_results:
                keyword_results = self._keyword_search.search(query, events, top_k)
                for sr in keyword_results:
                    eid = sr.event.get("id", "")
                    if eid not in seen_ids and len(results) < top_k:
                        seen_ids.add(eid)
                        results.append(SearchResult(event=sr.event, score=0.0))
        else:
            matched = self._keyword_search.search(query, events, top_k)
            results = list(matched)
        return results[:top_k]

    def get_history(self, limit: int = 10) -> list[MemoryEvent]:
        events = self._storage.read_events()
        if limit <= 0:
            return []
        return [MemoryEvent(**e) for e in events[-limit:]]

    def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        self._feedback.update_feedback(event_id, feedback)

    def write_interaction(self, query: str, response: str, event_type: str = "reminder") -> str:
        return self._interaction.write_interaction(query, response, event_type)
```

- [ ] **Step 4: 重写 memory_bank_store.py**

组合 EventStorage + MemoryBankEngine + FeedbackManager。提供 `events_store` / `strategies_store` / `summaries_store` / `interactions_store` 属性代理。

```python
class MemoryBankStore:
    store_name = "memorybank"
    requires_embedding = True
    requires_chat = True
    supports_interaction = True

    def __init__(self, data_dir, embedding_model=None, chat_model=None):
        self._storage = EventStorage(data_dir)
        self._engine = MemoryBankEngine(data_dir, self._storage, embedding_model, chat_model)
        self._feedback = FeedbackManager(data_dir)
        self.embedding_model = embedding_model
        self.chat_model = chat_model

    @property
    def events_store(self): return self._storage._store
    @property
    def strategies_store(self): return self._feedback._strategies_store
    @property
    def summaries_store(self): return self._engine._summaries_store
    @property
    def interactions_store(self): return self._engine._interactions_store

    def write(self, event): return self._engine.write(event)
    def search(self, query, top_k=10): return self._engine.search(query, top_k)
    def get_history(self, limit=10): ...  # 与 KeywordMemoryStore 同
    def update_feedback(self, event_id, feedback): self._feedback.update_feedback(event_id, feedback)
    def write_interaction(self, query, response, event_type="reminder"): return self._engine.write_interaction(query, response, event_type)
```

- [ ] **Step 5: 更新 stores/__init__.py**

移除 `BaseMemoryStore` 导出，保留其他四个。

- [ ] **Step 6: 更新 memory.py 注册表类型**

```python
_STORES_REGISTRY: dict[MemoryMode, type] = {}

def register_store(name: MemoryMode, store_cls: type) -> None:
    if name in _STORES_REGISTRY:
        return
    _STORES_REGISTRY[name] = store_cls

# _create_store 中:
if getattr(store_cls, 'requires_embedding', False):
    ...
if getattr(store_cls, 'requires_chat', False):
    ...
```

- [ ] **Step 7: 删除 stores/base.py**

```bash
rm app/memory/stores/base.py
```

- [ ] **Step 8: 运行全量测试**

Run: `uv run pytest tests/ -v --timeout=60`
Expected: ALL PASS

- [ ] **Step 9: Lint**

Run: `uv run ruff check app/memory/ tests/ --fix`
Expected: 无错误

- [ ] **Step 10: Commit**

```bash
git add app/memory/ tests/
git commit -m "refactor: rewrite stores as composition of components, delete BaseMemoryStore"
```

---

## Task 4: 测试适配

**Files:**
- Modify: `tests/test_memory_store_contract.py`
- Modify: `tests/test_memory_bank.py`
- Modify: `tests/stores/test_keyword_store.py`
- Modify: `tests/stores/test_memory_bank_store.py`

- [ ] **Step 1: 验证测试是否通过**

Task 3 完成后运行 `uv run pytest tests/ -v --timeout=60`。由于属性代理已提供，大部分测试应已通过。

- [ ] **Step 2: 修复任何失败的测试**

根据测试输出逐一修复。主要关注：
- 属性代理是否正确返回 JSONStore 实例
- import 路径是否从 `stores.base` 迁移完毕

- [ ] **Step 3: 运行全量测试确认**

Run: `uv run pytest tests/ -v --timeout=60`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "test: adapt tests to composition-based stores"
```

---

## Task 5: Loader 层重构（独立）

**Files:**
- Create: `app/experiment/loaders/base.py`
- Modify: `app/experiment/loaders/sgd_calendar.py`
- Modify: `app/experiment/loaders/scheduler.py`
- Modify: `app/experiment/loaders/__init__.py`
- Modify: `app/experiment/runners/prepare.py`
- Modify: `tests/test_prepare.py`

- [ ] **Step 1: 创建 loaders/base.py — DatasetLoader Protocol**

```python
"""DatasetLoader Protocol 定义."""

from typing import Protocol
from datasets import Dataset


class DatasetLoader(Protocol):
    """数据集加载器接口."""

    def load(self) -> Dataset: ...
    def get_test_cases(self) -> list[dict]: ...
```

- [ ] **Step 2: 重写 sgd_calendar.py — @classmethod → 实例方法**

将 `_cache` 从类变量改为模块级变量，所有 `@classmethod` 改为实例方法。删除模块级 `get_sgd_calendar_test_cases()` 函数（改由注册表 `get_test_cases()` 替代）：

```python
_cache = None

class SGDCalendarLoader:
    def load(self) -> Dataset:
        global _cache
        if _cache is None:
            _cache = load_dataset("vidhikatkoria/SGD_Calendar", split="train")
        ...
        return _cache

    def get_test_cases(self) -> list[dict]:
        ds = self.load()
        ...
```

- [ ] **Step 3: 重写 scheduler.py — 同上模式**

同样将 `@classmethod` 改为实例方法，`_cache` 改为模块级变量，删除模块级 `get_scheduler_test_cases()` 函数。

- [ ] **Step 4: 重写 loaders/__init__.py — 注册表**

```python
"""数据集加载器模块."""

from typing import Callable
from app.experiment.loaders.base import DatasetLoader
from app.experiment.loaders.sgd_calendar import SGDCalendarLoader
from app.experiment.loaders.scheduler import SchedulerLoader


_LOADERS: dict[str, Callable[[], DatasetLoader]] = {
    "sgd_calendar": SGDCalendarLoader,
    "scheduler": SchedulerLoader,
}


def get_test_cases(dataset: str) -> list[dict]:
    if dataset not in _LOADERS:
        raise ValueError(f"Unknown dataset: {dataset}")
    return _LOADERS[dataset]().get_test_cases()
```

- [ ] **Step 5: 更新 prepare.py — _load_dataset 改用注册表**

删除旧的 `from app.experiment.loaders.sgd_calendar import get_sgd_calendar_test_cases` 和 `from app.experiment.loaders.scheduler import get_scheduler_test_cases` 导入。替换为：

```python
from app.experiment.loaders import get_test_cases

def _load_dataset(name: str) -> list[dict[str, Any]]:
    return get_test_cases(name)
```

- [ ] **Step 6: 更新 test_prepare.py — patch 路径**

所有 `@patch("app.experiment.runners.prepare._load_dataset")` 改为 `@patch("app.experiment.loaders.get_test_cases")`。mock 侧边效果改为返回列表。删除旧的 `from app.experiment.loaders.sgd_calendar import ...` 和 `from app.experiment.loaders.scheduler import ...` 直接调用。

- [ ] **Step 7: 运行全量测试**

Run: `uv run pytest tests/ -v --timeout=60`
Expected: ALL PASS

- [ ] **Step 8: Lint**

Run: `uv run ruff check app/experiment/ tests/test_prepare.py --fix`
Expected: 无错误

- [ ] **Step 9: Commit**

```bash
git add app/experiment/ tests/test_prepare.py
git commit -m "refactor: loaders use Protocol + registry instead of static dispatch"
```

---

## Task 6: 最终验证

- [ ] **Step 1: 全量测试**

Run: `uv run pytest tests/ -v --timeout=60`
Expected: ALL PASS

- [ ] **Step 2: Lint 全量**

Run: `uv run ruff check app/ tests/ --fix`
Expected: 无错误

- [ ] **Step 3: 确认无残留 import**

Run: `rg "from app.memory.stores.base import" app/ tests/`
Run: `rg "BaseMemoryStore" app/ tests/`
Expected: 无结果
