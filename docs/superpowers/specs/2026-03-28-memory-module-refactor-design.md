# MemoryModule 重构设计文档

**日期**: 2026-03-28
**状态**: 设计中
**目标**: 拆分职责，创建统一的 MemoryStore 接口

---

## 1. 问题背景

### 1.1 现状

`MemoryModule`（`app/memory/memory.py`）和 `MemoryBankBackend`（`app/memory/memory_bank.py`）存在职责边界模糊问题：

```
MemoryModule
├── events_store (自有)
├── _memorybank_backend (MemoryBankBackend 实例)
│   ├── events_store (另一个!)
│   ├── interactions_store
│   └── summaries_store
```

**核心问题**：
1. 两套独立的 `events_store` 实例，数据不一致
2. `write()` 写入自己的 store，`write_interaction()` 写入 Backend 的 store
3. 三种 mode（keyword/llm_only/embeddings）混在 `MemoryModule` 一个类中，违背单一职责

### 1.2 影响

- 数据持久化可能丢失（写入 Backend 的数据，MemoryModule 自己的 store 不知道）
- 难以测试和 mock
- 扩展新检索模式困难
- 违反开闭原则：每新增一种 mode 都要修改 `MemoryModule`

---

## 2. 设计目标

1. **统一接口**：所有记忆操作通过同一接口访问
2. **单一数据源**：消除重复存储实例，每个 Store 管理自己的存储
3. **可测试性**：便于单元测试和 mock
4. **可扩展性**：便于添加新的检索模式，无需修改现有类
5. **最小改动**：在合理范围内减少重构风险

---

## 3. 接口设计

### 3.1 MemoryStore 抽象接口

```python
# app/memory/interfaces.py

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.chat import ChatModel
    from app.models.embedding import EmbeddingModel


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

### 3.2 各实现类职责

| 类名 | 存储文件 | 核心逻辑 |
|------|----------|----------|
| `KeywordMemoryStore` | events.json | 关键词大小写不敏感匹配 |
| `LLMOnlyMemoryStore` | events.json | LLM 判断语义相关性 |
| `EmbeddingMemoryStore` | events.json | 向量余弦相似度 > 0.7 |
| `MemoryBankStore` | events.json + interactions.json + memorybank_summaries.json | 遗忘曲线 + 分层摘要 + 交互聚合 |

### 3.3 统一 MemoryStore 基类

由于 `write_interaction` 是 `MemoryBankStore` 特有功能（其他 store 不支持交互聚合），将其下沉到 `MemoryBankStore`，不在接口中定义。

```python
# app/memory/stores/base.py

from abc import ABC
from app.memory.interfaces import MemoryStore
from app.storage.json_store import JSONStore


class BaseMemoryStore(MemoryStore, ABC):
    """MemoryStore 基类，提供共享的 events_store 和通用逻辑."""

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

### 3.4 MemoryModule 重构为 Facade

```python
# app/memory/memory.py

_STORES_REGISTRY: dict[str, type[BaseMemoryStore]] = {}


def register_store(name: str, store_cls: type[BaseMemoryStore]) -> None:
    """注册 MemoryStore 实现类，用于工厂创建."""
    _STORES_REGISTRY[name] = store_cls


class MemoryModule:
    """统一记忆管理接口，Facade 模式."""

    def __init__(
        self,
        data_dir: str,
        embedding_model: Optional[EmbeddingModel] = None,
        chat_model: Optional[ChatModel] = None,
    ):
        self._stores: dict[str, BaseMemoryStore] = {}
        self._data_dir = data_dir
        self._embedding_model = embedding_model
        self._chat_model = chat_model
        self._default_mode: str = "memorybank"

    def _get_store(self, mode: str) -> BaseMemoryStore:
        """懒加载获取指定模式的 store."""
        if mode not in self._stores:
            self._stores[mode] = self._create_store(mode)
        return self._stores[mode]

    def _create_store(self, mode: str) -> BaseMemoryStore:
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
        if not isinstance(store, MemoryBankStore):
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

---

## 4. 独立 Store 实现

### 4.1 KeywordMemoryStore

```python
# app/memory/stores/keyword_store.py

import uuid
from datetime import datetime
from app.memory.stores.base import BaseMemoryStore
from app.memory.interfaces import register_store


class KeywordMemoryStore(BaseMemoryStore):
    """关键词匹配检索 store."""

    @property
    def store_name(self) -> str:
        return "keyword"

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


register_store("keyword", KeywordMemoryStore)
```

### 4.2 LLMOnlyMemoryStore

```python
# app/memory/stores/llm_store.py

import uuid
import json
import re
import logging
from datetime import datetime
from typing import Optional
from app.memory.stores.base import BaseMemoryStore
from app.memory.interfaces import register_store
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
        chat_model: Optional[ChatModel] = None,
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


register_store("llm_only", LLMOnlyMemoryStore)
```

### 4.3 EmbeddingMemoryStore

```python
# app/memory/stores/embedding_store.py

import uuid
from datetime import datetime
from typing import Optional
from app.memory.stores.base import BaseMemoryStore
from app.memory.interfaces import register_store
from app.models.embedding import EmbeddingModel
from app.memory.utils import cosine_similarity


class EmbeddingMemoryStore(BaseMemoryStore):
    """向量相似度检索 store."""

    def __init__(
        self,
        data_dir: str,
        embedding_model: Optional[EmbeddingModel] = None,
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


register_store("embeddings", EmbeddingMemoryStore)
```

### 4.4 MemoryBankStore

从 `memory_bank.py` 迁移，实现 `MemoryStore` 接口：

```python
# app/memory/stores/memory_bank_store.py

import math
import uuid
from datetime import date, datetime
from typing import Optional
from app.memory.stores.base import BaseMemoryStore
from app.memory.interfaces import register_store
from app.models.embedding import EmbeddingModel
from app.models.chat import ChatModel
from app.memory.utils import cosine_similarity

AGGREGATION_SIMILARITY_THRESHOLD = 0.8
DAILY_SUMMARY_THRESHOLD = 5
OVERALL_SUMMARY_THRESHOLD = 3
SUMMARY_WEIGHT = 0.8
TOP_K = 3


def forgetting_curve(days_elapsed: int, strength: int) -> float:
    if days_elapsed <= 0:
        return 1.0
    return math.exp(-days_elapsed / (5 * strength))


class MemoryBankStore(BaseMemoryStore):
    """遗忘曲线 + 分层摘要 store."""

    def __init__(
        self,
        data_dir: str,
        embedding_model: Optional[EmbeddingModel] = None,
        chat_model: Optional[ChatModel] = None,
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

    # ... 其他私有方法迁移 ...

    def _maybe_summarize(self, date_group: str) -> None:
        # ... 保持原有逻辑 ...
        pass


register_store("memorybank", MemoryBankStore)
```

---

## 5. 文件结构

```
app/memory/
├── __init__.py                    # 导出 MemoryModule, register_store
├── interfaces.py                  # 新增：MemoryStore ABC
├── memory.py                      # 重构：Facade + 工厂注册表
├── memory_bank.py                 # 删除：迁移到 stores/
├── utils.py                       # 保留：cosine_similarity
└── stores/
    ├── __init__.py                # 导入所有 store 类
    ├── base.py                    # 新增：BaseMemoryStore
    ├── keyword_store.py           # 新增：KeywordMemoryStore
    ├── llm_store.py               # 新增：LLMOnlyMemoryStore
    ├── embedding_store.py         # 新增：EmbeddingMemoryStore
    └── memory_bank_store.py       # 新增：从 memory_bank.py 迁移
```

---

## 6. 迁移步骤

### Step 1: 创建接口层
- 创建 `interfaces.py` 定义 `MemoryStore` ABC
- 创建 `stores/base.py` 定义 `BaseMemoryStore`

### Step 2: 实现三种独立 Store
- 创建 `stores/keyword_store.py`
- 创建 `stores/llm_store.py`
- 创建 `stores/embedding_store.py`
- 在 `__init__.py` 中注册到全局注册表

### Step 3: 迁移 MemoryBankStore
- 将 `memory_bank.py` 重写为 `stores/memory_bank_store.py`
- 实现 `MemoryStore` 接口
- 保留所有原有逻辑（遗忘曲线、摘要等）

### Step 4: 重构 MemoryModule
- 删除 `MemoryModule` 内的 search 实现代码
- 实现 Facade + 工厂注册表
- 确保 `write()` 和 `write_interaction()` 使用同一默认模式

### Step 5: 接口契约测试
- 创建 `test_memory_store_contract.py` 验证所有实现满足接口契约

### Step 6: 集成测试迁移
- 迁移 `test_memory_bank.py` 到新结构

---

## 7. 测试策略

### 7.1 接口契约测试（必须）

```python
# tests/test_memory_store_contract.py

import pytest
from app.memory.interfaces import MemoryStore


class TestMemoryStoreContract:
    """验证所有 MemoryStore 实现满足接口契约."""

    @pytest.fixture(params=["keyword", "llm_only", "embeddings", "memorybank"])
    def store(self, request, tmp_path):
        from app.memory.memory import MemoryModule
        mm = MemoryModule(str(tmp_path))
        return mm._get_store(request.param)

    def test_write_returns_string_id(self, store):
        event_id = store.write({"content": "test"})
        assert isinstance(event_id, str)

    def test_write_then_read_returns_same_event(self, store):
        event_id = store.write({"content": "测试事件"})
        events = store.events_store.read()
        assert any(e["id"] == event_id for e in events)

    def test_get_history_returns_list(self, store):
        store.write({"content": "事件1"})
        history = store.get_history(limit=10)
        assert isinstance(history, list)

    def test_get_history_respects_limit(self, store):
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

### 7.2 各 Store 独立测试

| 测试文件 | 覆盖内容 |
|----------|----------|
| `test_keyword_store.py` | 关键词匹配、大小写不敏感 |
| `test_llm_store.py` | LLM 调用 fallback、异常处理 |
| `test_embedding_store.py` | 向量相似度阈值、keyword fallback |
| `test_memory_bank_store.py` | 遗忘曲线、层级摘要、交互聚合 |

### 7.3 Facade 路由测试

```python
# tests/test_memory_module_facade.py

def test_search_routes_to_correct_store(tmp_path):
    mm = MemoryModule(str(tmp_path))
    mm.write({"content": "测试"})
    assert len(mm.search("测试", mode="keyword")) == 1

def test_default_mode_is_memorybank(tmp_path):
    mm = MemoryModule(str(tmp_path))
    assert mm._default_mode == "memorybank"

def test_write_uses_default_mode(tmp_path):
    mm = MemoryModule(str(tmp_path))
    mm.write({"content": "事件"})
    events = mm.get_history()
    assert len(events) == 1
```

---

## 8. 向后兼容

### 8.1 API 兼容

| 方法 | 签名变化 | 说明 |
|------|----------|------|
| `__init__` | 无变化 | 一致 |
| `write(event)` | 无变化 | 一致 |
| `search(query, mode)` | `mode` 参数变为可选，默认使用 `memorybank` | 兼容 |
| `get_history(limit)` | 无变化 | 一致 |
| `update_feedback(event_id, feedback)` | 无变化 | 一致 |

### 8.2 新增 API

| 方法 | 说明 |
|------|------|
| `set_default_mode(mode)` | 设置默认模式 |
| `write_interaction(query, response, event_type)` | 写入交互记录（仅 memorybank 支持） |

### 8.3 行为变化

- `write_interaction()` 现在必须显式使用 `mode="memorybank"` 或设置默认模式为 `memorybank`
- `search()` 不传 mode 时使用 `memorybank` 而非 `keyword`（行为更安全）

---

## 9. 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| 改动范围大 | 分步骤提交，每个 step 可独立测试 |
| 数据丢失 | 保持 JSONStore 格式不变 |
| 接口不匹配 | 编写接口契约测试 |
| 注册表初始化顺序 | 在 `__init__.py` 中确保所有 store 已注册 |

---

## 10. 决策记录

| 日期 | 决策 | 理由 |
|------|------|------|
| 2026-03-28 | 采用方案B | 职责清晰，便于扩展 |
| 2026-03-28 | 三种 mode 拆分为独立类 | 符合单一职责，利于测试和扩展 |
| 2026-03-28 | 使用注册表模式替代硬编码工厂 | 符合开闭原则，新增 store 不需修改 MemoryModule |
| 2026-03-28 | write_interaction 收归 MemoryBankStore | 其他 store 不支持交互语义 |
| 2026-03-28 | 默认模式改为 memorybank | 与 `write_interaction` 语义一致 |
