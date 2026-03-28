# 记忆后端类型定义全面重构设计

## 问题概述

当前记忆后端类型体系存在 11 个问题（P0-P2），核心表现为：

- **P0 Bug**: `_strengthen_events()` 双重递增，`memory_strength` 每次搜索 +2 而非 +1
- **P1 代码重复**: `write()` 在 3 个 Store 中完全重复；关键词搜索逻辑在 2 个 Store 中重复
- **P1 一致性**: `search()` 签名不一致（MemoryBankStore 多了 `top_k`）；`write()` 浅拷贝行为不一致
- **P2 语义**: `write_interaction()` 默认实现丢弃 `query`；搜索结果泄漏 `_score`、`_source` 内部字段
- **P2 健壮性**: ABC 属性无默认值，直接实现接口会报错

## 方案选择

**方案 B: Pydantic 模型 + 接口统一**

引入 Pydantic 数据模型定义类型契约，统一接口签名，消费者直接使用类型化接口。

## 设计

### 1. 数据模型层 — `app/memory/schemas.py`（新增）

新增 Pydantic schemas 文件，定义所有记忆相关数据模型。

```python
from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional


class MemoryEvent(BaseModel):
    """记忆事件数据模型."""

    id: str = ""
    created_at: str = ""
    content: str = ""
    type: str = "reminder"
    description: str = ""

    model_config = ConfigDict(extra="allow")


class InteractionRecord(BaseModel):
    """交互记录数据模型."""

    id: str = ""
    event_id: str = ""
    query: str = ""
    response: str = ""
    timestamp: str = ""
    memory_strength: int = 1
    last_recall_date: str = ""


class FeedbackData(BaseModel):
    """反馈数据模型."""

    event_id: str = ""
    action: str = ""
    type: str = "default"
    timestamp: str = ""

    model_config = ConfigDict(extra="allow")


class SearchResult(BaseModel):
    """搜索结果包装器，隔离内部评分字段与原始事件数据."""

    event: dict = Field(default_factory=dict)
    score: float = 0.0
    source: str = "event"
    interactions: list[dict] = Field(default_factory=list)

    def to_public(self) -> dict:
        """返回不含内部字段的纯事件数据（含 interactions）."""
        result = dict(self.event)
        if self.interactions:
            result["interactions"] = self.interactions
        return result
```

设计要点：
- `MemoryEvent` 使用 `extra="allow"` 允许 MemoryBankStore 追加 `memory_strength`、`date_group`、`interaction_ids` 等扩展字段
- `SearchResult` 将 `_score`、`_source`、`interactions` 与原始事件分离，`to_public()` 返回干净的 event dict
- `FeedbackData` 使用 `extra="allow"` 允许扩展 `modified_content` 等字段

### 2. 接口层重构 — `app/memory/interfaces.py`

```python
class MemoryStore(ABC):
    """记忆存储抽象接口."""

    requires_embedding: bool = False    # ABC 层提供默认值
    requires_chat: bool = False
    supports_interaction: bool = False

    @property
    @abstractmethod
    def store_name(self) -> str: ...

    @abstractmethod
    def write(self, event: MemoryEvent) -> str: ...

    @abstractmethod
    def search(self, query: str, top_k: int = 10) -> list[SearchResult]: ...

    def get_history(self, limit: int = 10) -> list[MemoryEvent]: ...

    def update_feedback(self, event_id: str, feedback: FeedbackData) -> None: ...

    def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str: ...
```

变更点：
- 3 个布尔属性添加默认值 `False`
- `write()` 参数从 `dict` 改为 `MemoryEvent`
- `search()` 统一签名，添加 `top_k` 参数，返回 `list[SearchResult]`
- `get_history()` 返回 `list[MemoryEvent]`
- `update_feedback()` 的 `feedback` 参数改为 `FeedbackData`

### 3. 基类重构 — `app/memory/stores/base.py`

```python
class BaseMemoryStore(MemoryStore, ABC):
    requires_embedding: bool = False
    requires_chat: bool = False
    supports_interaction: bool = False

    def __init__(self, data_dir: str, embedding_model=None, chat_model=None) -> None:
        self.data_dir = data_dir
        self.events_store = JSONStore(data_dir, "events.json", list)
        self.strategies_store = JSONStore(data_dir, "strategies.json", dict)

    # ——— write() 默认实现（消除 3 个 Store 重复） ———
    def write(self, event: MemoryEvent) -> str:
        event = event.model_copy(deep=True)
        event.id = self._generate_id()
        event.created_at = datetime.now().isoformat()
        self.events_store.append(event.model_dump())
        return event.id

    def _generate_id(self) -> str:
        return f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

    # ——— search() 默认实现（关键词搜索） ———
    def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        events = self.events_store.read()
        matched = self._keyword_search(query, events)
        return [SearchResult(event=e) for e in matched[:top_k]]

    def _keyword_search(self, query: str, events: list[dict]) -> list[dict]:
        """基础关键词搜索（匹配 content + description）."""
        query_lower = query.lower()
        return [
            e for e in events
            if query_lower in e.get("content", "").lower()
            or query_lower in e.get("description", "").lower()
        ]

    # ——— get_history() ———
    def get_history(self, limit: int = 10) -> list[MemoryEvent]:
        events = self.events_store.read()
        if limit <= 0:
            return []
        return [MemoryEvent(**e) for e in events[-limit:]]

    # ——— update_feedback() ———
    def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        feedback.event_id = event_id
        feedback.timestamp = datetime.now().isoformat()
        feedback_store = JSONStore(self.data_dir, "feedback.json", list)
        feedback_store.append(feedback.model_dump())
        self._update_strategy(event_id, feedback.model_dump())

    # ——— write_interaction() ———
    def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str:
        """默认实现：将交互记录作为普通事件写入（保留 query）.

        与当前行为不同，query 不再被丢弃，而是作为事件的 description 存储。
        不支持交互的 Store 可重写为 NotImplementedError。
        """
        event = MemoryEvent(
            content=response,
            type=event_type,
            description=query,
        )
        return self.write(event)

    # ——— _update_strategy()（内部逻辑不变） ———
    def _update_strategy(self, event_id: str, feedback: dict) -> None:
        ...  # 保持现有实现
```

变更点：
- `write()` 提取为基类默认实现，子类可重写
- `search()` 提供关键词搜索默认实现
- `_keyword_search()` 提取为共享的 protected 方法
- `write_interaction()` 不支持时抛 `NotImplementedError`
- `get_history()` 返回 `list[MemoryEvent]`
- `update_feedback()` 接受 `FeedbackData`

### 4. 子类简化

| Store | write() | search() | write_interaction() | 其他 |
|---|---|---|---|---|
| `KeywordMemoryStore` | 继承基类 | 继承基类（关键词） | 继承基类（作为事件写入） | 无 |
| `LLMOnlyMemoryStore` | 继承基类 | **重写**（LLM 语义判断） | 继承基类（作为事件写入） | 无 |
| `EmbeddingMemoryStore` | 继承基类 | **重写**（向量相似度 + keyword fallback） | 继承基类（作为事件写入） | 无 |
| `MemoryBankStore` | **重写**（追加 memory_strength 等字段） | **重写**（遗忘曲线 + 摘要） | **重写**（完整交互逻辑） | 修复 P0 Bug |

#### MemoryBankStore 关键修复

**P0 Bug 修复** — `_strengthen_events()` 移除第二次循环：

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
    # ← 删除第 188-191 行的第二次循环
    self._strengthen_interactions(matched_ids)
```

**搜索结果封装** — `_search_by_keyword` / `_search_by_embedding` / `_search_summaries` 返回 `SearchResult`：

```python
def _search_by_keyword(self, query, events, top_k) -> list[SearchResult]:
    ...
    results.append(SearchResult(event=dict(event), score=retention, source="event"))
    ...

def _search_summaries(self, query, daily_summaries, top_k=1) -> list[SearchResult]:
    ...
    results.append(SearchResult(
        event={"content": content, "date_group": date_group, ...},
        score=score,
        source="daily_summary",
    ))
    ...
```

**`_expand_event_interactions()` 适配**：该方法负责将 interactions 附加到搜索结果上。重构后直接填充 `SearchResult.interactions` 字段：

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

**search() 完整流程**：

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

**write() 完整实现**（不调用 super，独立处理 MemoryBank 专有字段）：

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

### 5. MemoryModule 变更 — `app/memory/memory.py`

```python
class MemoryModule:
    def write(self, event: MemoryEvent) -> str:
        return self._get_store(self._default_mode).write(event)

    def write_interaction(self, query: str, response: str,
                          event_type: str = "reminder") -> str:
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

**注册表去重保护**：

```python
def register_store(name: MemoryMode, store_cls: type[MemoryStore]) -> None:
    if name in _STORES_REGISTRY:
        return
    _STORES_REGISTRY[name] = store_cls
```

### 6. 消费者适配

#### `AgentWorkflow._context_node`

搜索结果和历史记录在存入 `context` 时需序列化为 dict，因为下游 `_task_node` / `_strategy_node` 调用 `json.dumps(context)` 会失败于 Pydantic 对象。

```python
related_events = self.memory_module.search(user_input, mode=self.memory_mode)
if related_events:
    relevant_data = [e.to_public() for e in related_events]
else:
    relevant_data = [e.model_dump() for e in self.memory_module.get_history()]
prompt = f"... 历史记录: {json.dumps(relevant_data, ensure_ascii=False)}"

context = self._call_llm_json(prompt)
context["related_events"] = relevant_data        # dict 列表，可 json.dumps
context["relevant_memories"] = relevant_data
```

#### `API /api/history`

```python
@app.get("/api/history")
async def history(limit: int = 10, mm = Depends(get_memory_module)):
    events = mm.get_history(limit=limit)
    return {"history": [e.model_dump() for e in events]}
```

#### `API /api/feedback`

```python
@app.post("/api/feedback")
async def feedback(request: FeedbackRequest, mm = Depends(get_memory_module)):
    feedback = FeedbackData(
        event_id=request.event_id,
        action=request.action,
        modified_content=request.modified_content,
    )
    mm.update_feedback(request.event_id, feedback)
    return {"status": "success"}
```

### 7. 对比实验模块 — 无需修改

`app/experiment/runner.py` 和 `run_experiment.py` **不需要任何修改**，原因：

1. `ExperimentRunner` 只通过 `create_workflow()` → `AgentWorkflow` 间接使用 MemoryModule，自身不调用 MemoryModule 方法
2. `_extract_scoring_output()` 直接读 `events.json` 原始 dict — `event.model_dump()` 写入的仍然是纯 dict，JSON 兼容
3. `_reset_events_store()` 写 `[]` — 无影响
4. `run_experiment.py` 只使用 `MemoryMode` 枚举 — 无影响

唯一间接影响路径是 `AgentWorkflow._context_node`（已在第 6 节覆盖）。

## 变更文件清单

| 文件 | 操作 | 说明 |
|---|---|---|
| `app/memory/schemas.py` | 新增 | Pydantic 数据模型 |
| `app/memory/interfaces.py` | 修改 | 接口签名类型化 |
| `app/memory/stores/base.py` | 修改 | write/search 默认实现、keyword_search 提取 |
| `app/memory/stores/keyword_store.py` | 修改 | 大幅简化，继承基类 |
| `app/memory/stores/llm_store.py` | 修改 | 删除 write 重复，search 返回 SearchResult |
| `app/memory/stores/embedding_store.py` | 修改 | 删除 write 重复，search 返回 SearchResult |
| `app/memory/stores/memory_bank_store.py` | 修改 | 修复 P0 Bug，search 返回 SearchResult |
| `app/memory/memory.py` | 修改 | MemoryModule 类型签名更新 |
| `app/memory/__init__.py` | 修改 | 导出 schemas |
| `app/agents/workflow.py` | 修改 | 适配 SearchResult / MemoryEvent |
| `app/api/main.py` | 修改 | 适配 MemoryEvent / FeedbackData |
| `tests/` | 修改 | 适配新类型签名 |

以下文件**无需修改**：

| 文件 | 原因 |
|---|---|
| `app/experiment/runner.py` | 间接通过 AgentWorkflow 使用，直接读 JSON |
| `run_experiment.py` | 只使用 MemoryMode 枚举 |
| `app/storage/json_store.py` | 底层存储引擎，不涉及类型变更 |

## 未解决问题

无。
