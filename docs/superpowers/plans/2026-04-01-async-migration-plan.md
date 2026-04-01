# 全异步改造实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将项目内所有模块（除 vendor/）从同步形式改造为完全异步形式

**Architecture:** 自底向上逐层异步化：存储层 → 模型层 → 接口层 → 业务层 → 工作流层 → API层

**Tech Stack:** Python asyncio, aiofiles, pytest-asyncio

---

## 文件结构

```
app/storage/json_store.py          # 异步文件IO
app/models/embedding.py            # async encode/batch_encode
app/models/chat.py                 # async generate
app/memory/interfaces.py           # MemoryStore Protocol 改为 async
app/memory/components.py            # EventStorage/FeedbackManager/MemoryBankEngine 改为 async
app/memory/stores/memory_bank_store.py  # 实现 async
app/memory/memory.py               # MemoryModule Facade async
app/agents/workflow.py              # AgentWorkflow async
app/api/main.py                    # API await 调用
```

---

## Task 1: JSONStore 异步化

**Files:**
- Modify: `app/storage/json_store.py`

- [ ] **Step 1: 添加 aiofiles 依赖**

修改 `pyproject.toml`，在 dependencies 中添加：
```toml
"aiofiles>=24.1.0",
```

- [ ] **Step 2: 将 JSONStore 改为全异步**

```python
import aiofiles
import json
from pathlib import Path
from typing import Any, Callable, TypeVar

T = TypeVar("T")

class JSONStore:
    def __init__(
        self,
        data_dir: Path,
        filename: Path,
        default_factory: Callable[[], T] = lambda: dict(),
    ) -> None:
        self.filepath = filename if filename.is_absolute() else data_dir / filename
        self.default_factory = default_factory

    def _ensure_file(self) -> None:
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        if not self.filepath.exists():
            import asyncio
            asyncio.run(self._async_write(self.default_factory()))

    async def _async_write(self, data: T) -> None:
        async with aiofiles.open(self.filepath, "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, ensure_ascii=False, indent=2))

    async def read(self) -> T:
        async with aiofiles.open(self.filepath, "r", encoding="utf-8") as f:
            content = await f.read()
        return json.loads(content)

    async def write(self, data: T) -> None:
        await self._async_write(data)

    async def append(self, item: Any) -> None:
        data = await self.read()
        if not isinstance(data, list):
            raise TypeError(f"append() requires list factory, got {type(data).__name__}")
        data.append(item)
        await self._async_write(data)

    async def update(self, key: str, value: Any) -> None:
        data = await self.read()
        if not isinstance(data, dict):
            raise TypeError(f"update() requires dict factory, got {type(data).__name__}")
        data[key] = value
        await self._async_write(data)
```

- [ ] **Step 3: 验证 JSONStore 改动**

运行: `uv run pytest tests/test_storage.py -v`

- [ ] **Step 4: 提交**

```bash
git add app/storage/json_store.py pyproject.toml
git commit -m "feat: JSONStore 改为全异步，使用 aiofiles"
```

---

## Task 2: EmbeddingModel 异步化

**Files:**
- Modify: `app/models/embedding.py`

- [ ] **Step 1: 添加 asyncio.to_thread 封装**

在 `EmbeddingModel` 类中添加：

```python
import asyncio

class EmbeddingModel:
    async def encode(self, text: str) -> list[float]:
        return await asyncio.to_thread(self._sync_encode, text)
    
    async def batch_encode(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self._sync_batch_encode, texts)
    
    def _sync_encode(self, text: str) -> list[float]:
        cl = self.client
        provider = self._active_provider_or_raise()
        if isinstance(cl, openai.OpenAI):
            return self._encode_with_openai(cl, provider.provider.model, text)
        return self._encode_with_local(cl, text)
    
    def _sync_batch_encode(self, texts: list[str]) -> list[list[float]]:
        cl = self.client
        provider = self._active_provider_or_raise()
        if isinstance(cl, openai.OpenAI):
            return self._batch_encode_with_openai(cl, provider.provider.model, texts)
        return self._batch_encode_with_local(cl, texts)
```

- [ ] **Step 2: 验证 EmbeddingModel 改动**

运行: `uv run pytest tests/test_embedding.py -v`

- [ ] **Step 3: 提交**

```bash
git add app/models/embedding.py
git commit -m "feat: EmbeddingModel 添加 async encode/batch_encode"
```

---

## Task 3: ChatModel async generate

**Files:**
- Modify: `app/models/chat.py`

- [ ] **Step 1: 添加 async generate 方法**

在 `ChatModel` 类中原同步 `generate` 方法保持不变（等所有调用方迁移完再删），新增 async 版本：

```python
async def generate(
    self,
    prompt: str,
    system_prompt: str | None = None,
    **_kwargs: object,
) -> str:
    """异步生成回复"""
    messages = self._build_messages(prompt, system_prompt)
    errors = []
    for provider in self.providers:
        try:
            client = self._create_async_client(provider)
            response = await client.chat.completions.create(
                model=provider.provider.model,
                messages=messages,
                temperature=self._get_temperature(provider),
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            errors.append(f"{provider.provider.model}: {e}")
            continue
    raise RuntimeError(f"All LLM providers failed: {'; '.join(errors)}")
```

- [ ] **Step 2: 验证 ChatModel 改动**

运行: `uv run pytest tests/test_chat.py -v`

- [ ] **Step 3: 提交**

```bash
git add app/models/chat.py
git commit -m "feat: ChatModel 添加 async generate 方法"
```

---

## Task 4: MemoryStore Protocol 异步化

**Files:**
- Modify: `app/memory/interfaces.py`

- [ ] **Step 1: 将 Protocol 方法签名改为 async def**

```python
class MemoryStore(Protocol):
    store_name: str
    requires_embedding: bool
    requires_chat: bool
    supports_interaction: bool

    async def write(self, event: MemoryEvent) -> str: ...
    async def search(self, query: str, top_k: int = 10) -> list[SearchResult]: ...
    async def get_history(self, limit: int = 10) -> list[MemoryEvent]: ...
    async def update_feedback(self, event_id: str, feedback: FeedbackData) -> None: ...
    async def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str: ...
```

- [ ] **Step 2: 验证 ty 检查**

运行: `uv run ty check app/memory/interfaces.py`

- [ ] **Step 3: 提交**

```bash
git add app/memory/interfaces.py
git commit -m "refactor: MemoryStore Protocol 方法改为 async"
```

---

## Task 5: components.py 异步化

**Files:**
- Modify: `app/memory/components.py`

- [ ] **Step 1: EventStorage 公开方法改为 async**

```python
class EventStorage:
    async def append_event(self, event: MemoryEvent) -> str:
        event = event.model_copy(deep=True)
        event.id = self.generate_id()
        event.created_at = datetime.now(timezone.utc).isoformat()
        await self._store.append(event.model_dump())
        return event.id

    async def read_events(self) -> list[dict]:
        return await self._store.read()

    async def write_events(self, events: list[dict]) -> None:
        await self._store.write(events)
```

注意：`generate_id` 是纯计算，保持同步。

- [ ] **Step 2: FeedbackManager.update_feedback 改为 async**

```python
class FeedbackManager:
    async def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        feedback.event_id = event_id
        feedback.timestamp = datetime.now(timezone.utc).isoformat()
        feedback_store = JSONStore(self.data_dir, Path("feedback.json"), list)
        await feedback_store.append(feedback.model_dump())
        await self._update_strategy(event_id, feedback.model_dump())

    async def _update_strategy(self, event_id: str, feedback: dict) -> None:
        strategies = await self._strategies_store.read()
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

        await self._strategies_store.write(strategies)
```

- [ ] **Step 3: MemoryBankEngine 公开方法改为 async**

需要改的方法：`write`, `search`, `write_interaction`

内部调用的私有方法如果是纯计算保持同步，如果是调用了异步方法则需要 await。

重点改造：
```python
class MemoryBankEngine:
    async def write(self, event: MemoryEvent) -> str:
        event = event.model_copy(deep=True)
        event.id = self._storage.generate_id()
        event.created_at = datetime.now(timezone.utc).isoformat()
        today = datetime.now(timezone.utc).date().isoformat()
        event.memory_strength = 1
        event.last_recall_date = today
        event.date_group = today
        await self._storage._store.append(event.model_dump())
        await self._maybe_summarize(today)
        return event.id

    async def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        if not query.strip():
            return []
        events = await self._storage.read_events()
        summaries = await self._summaries_store.read()
        # ... 后续逻辑中调用 embedding.encode 等改为 await

    async def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str:
        # ... 涉及 self._interactions_store.append 等改为 await
```

**重要**：内部纯计算方法（`_strengthen_events`, `_search_by_keyword`, `_search_by_embedding`, `_maybe_summarize` 等）保持同步，因为无 IO。

- [ ] **Step 4: 验证 components 改动**

运行: `uv run ty check app/memory/components.py`

- [ ] **Step 5: 提交**

```bash
git add app/memory/components.py
git commit -m "feat: components.py EventStorage/FeedbackManager/MemoryBankEngine 改为 async"
```

---

## Task 6: MemoryBankStore 异步化

**Files:**
- Modify: `app/memory/stores/memory_bank_store.py`

- [ ] **Step 1: 所有公开方法改为 async**

```python
class MemoryBankStore:
    async def write(self, event: MemoryEvent) -> str:
        return await self._engine.write(event)

    async def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        return await self._engine.search(query, top_k)

    async def get_history(self, limit: int = 10) -> list[MemoryEvent]:
        events = await self._storage.read_events()
        if limit <= 0:
            return []
        return [MemoryEvent(**e) for e in events[-limit:]]

    async def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        await self._feedback.update_feedback(event_id, feedback)

    async def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str:
        return await self._engine.write_interaction(query, response, event_type)
```

- [ ] **Step 2: 验证 MemoryBankStore 改动**

运行: `uv run ty check app/memory/stores/memory_bank_store.py`

- [ ] **Step 3: 提交**

```bash
git add app/memory/stores/memory_bank_store.py
git commit -m "feat: MemoryBankStore 所有方法改为 async"
```

---

## Task 7: MemoryModule Facade 异步化

**Files:**
- Modify: `app/memory/memory.py`

- [ ] **Step 1: 所有公开方法改为 async**

```python
class MemoryModule:
    async def write(self, event: MemoryEvent) -> str:
        return await self._get_store(self._default_mode).write(event)

    async def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str:
        store = self._get_store(self._default_mode)
        if not getattr(store, "supports_interaction", False):
            raise NotImplementedError(
                f"Store '{store.store_name}' does not support write_interaction"
            )
        return await store.write_interaction(query, response, event_type)

    async def search(
        self, query: str, mode: MemoryMode | None = None, top_k: int = 10
    ) -> list[SearchResult]:
        target_mode = mode or self._default_mode
        return await self._get_store(target_mode).search(query, top_k=top_k)

    async def get_history(self, limit: int = 10) -> list[MemoryEvent]:
        return await self._get_store(self._default_mode).get_history(limit)

    async def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        await self._get_store(self._default_mode).update_feedback(event_id, feedback)
```

- [ ] **Step 2: 验证 MemoryModule 改动**

运行: `uv run ty check app/memory/memory.py`

- [ ] **Step 3: 提交**

```bash
git add app/memory/memory.py
git commit -m "feat: MemoryModule Facade 所有方法改为 async"
```

---

## Task 8: AgentWorkflow 异步化

**Files:**
- Modify: `app/agents/workflow.py`

- [ ] **Step 1: run 方法和节点方法改为 async**

```python
class AgentWorkflow:
    async def run(self, user_input: str) -> tuple[str, str | None]:
        state: AgentState = {
            "messages": [{"role": "user", "content": user_input}],
            "context": {},
            "task": {},
            "decision": {},
            "memory_mode": self.memory_mode,
            "result": None,
            "event_id": None,
        }

        for node_fn in self._nodes:
            updates = await node_fn(state)
            state.update(updates)

        result = state.get("result") or "处理完成"
        event_id = state.get("event_id")
        return result, event_id

    async def _context_node(self, state: AgentState) -> dict:
        # ... 内部调用改为 await
        related_events = (
            await self.memory_module.search(user_input, mode=self.memory_mode)
            if user_input
            else []
        )
        # ...
        context = await self._call_llm_json(prompt)
        # ...

    async def _task_node(self, state: AgentState) -> dict: ...
    async def _strategy_node(self, state: AgentState) -> dict: ...
    async def _execution_node(self, state: AgentState) -> dict: ...
```

- [ ] **Step 2: _call_llm_json 内部调用改为 await**

```python
def _call_llm_json(self, user_prompt: str) -> dict:
    if not self.memory_module.chat_model:
        raise RuntimeError("ChatModel not available")
    result = await self.memory_module.chat_model.generate(user_prompt)  # await async generate
    # ... JSON 解析逻辑
```

- [ ] **Step 3: 验证 AgentWorkflow 改动**

运行: `uv run ty check app/agents/workflow.py`

- [ ] **Step 4: 提交**

```bash
git add app/agents/workflow.py
git commit -m "feat: AgentWorkflow run 和节点方法改为 async"
```

---

## Task 9: API 层适配

**Files:**
- Modify: `app/api/main.py`

- [ ] **Step 1: 所有调用改为 await**

```python
@app.post("/api/query")
async def query(request: QueryRequest, mm: MemoryModule = Depends(get_memory_module)) -> dict:
    workflow = AgentWorkflow(
        data_dir=DATA_DIR,
        memory_mode=request.memory_mode,
        memory_module=mm,
    )
    result, event_id = await workflow.run(request.query)
    return {"result": result, "event_id": event_id}

@app.post("/api/feedback")
async def feedback(request: FeedbackRequest, mm: MemoryModule = Depends(get_memory_module)) -> dict:
    await mm.update_feedback(request.event_id, FeedbackData(...))
    return {"status": "success"}

@app.get("/api/history")
async def history(limit: int = 10, mm: MemoryModule = Depends(get_memory_module)) -> dict:
    events = await mm.get_history(limit=limit)
    return {"history": [e.model_dump() for e in events]}
```

- [ ] **Step 2: 验证 API 层改动**

运行: `uv run ty check app/api/main.py`

- [ ] **Step 3: 提交**

```bash
git add app/api/main.py
git commit -m "feat: API 层适配异步调用"
```

---

## Task 10: 测试异步化

**Files:**
- Modify: `tests/` 下各测试文件
- Modify: `pytest.ini`

- [ ] **Step 1: pytest.ini 添加 asyncio 配置**

```ini
[pytest]
asyncio_mode = auto
asyncio_default_fixture_loop_scope = function
```

- [ ] **Step 2: 将所有测试函数改为 async**

例如 `tests/test_storage.py`:
```python
import pytest

@pytest.mark.asyncio
async def test_json_store_append():
    store = JSONStore(data_dir, Path("test.json"), list)
    await store.append({"id": 1})
    data = await store.read()
    assert data == [{"id": 1}]
```

- [ ] **Step 3: 验证所有测试通过**

运行: `uv run pytest tests/ -v`

- [ ] **Step 4: 提交**

```bash
git add pytest.ini tests/
git commit -m "test: 所有测试改为异步模式"
```

---

## Task 11: 全量检查

- [ ] **Step 1: ruff check**

运行: `uv run ruff check --fix`

- [ ] **Step 2: ty check**

运行: `uv run ty check`

- [ ] **Step 3: ruff format**

运行: `uv run ruff format`

- [ ] **Step 4: pytest 完整测试**

运行: `uv run pytest tests/ -v`

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "chore: 全量lint/typecheck/format检查通过"
```

---

## Task 12: ChatModel 同步 generate 清理

**Files:**
- Modify: `app/models/chat.py`

- [ ] **Step 1: 删除同步 generate 方法**

所有调用方已迁移到 async generate，删除原同步方法。

- [ ] **Step 2: 验证**

运行: `uv run pytest tests/test_chat.py -v && uv run ty check app/models/chat.py`

- [ ] **Step 3: 提交**

```bash
git add app/models/chat.py
git commit -m "refactor: 删除 ChatModel 同步 generate 方法"
```
