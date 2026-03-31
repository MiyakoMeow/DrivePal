# 全异步改造设计文档

**日期**: 2026-04-01  
**状态**: 设计中  
**范围**: 除 `vendor/` 模块外的全部实现

---

## 1. 背景与目标

**需求**: 将项目内所有模块（除 vendor）从同步形式改造为完全异步形式。

**驱动因素**:
- 高并发需求：同时处理多个用户请求/大量 benchmark 任务
- LLM 调用延迟隐藏：ChatModel 已有 `generate_stream` 异步，但调用方是同步的，无法并发发起多个 LLM 请求

**约束**:
- `vendor/` 模块禁止修改
- 工作流节点保持串行执行
- 改造过程逐步推进，确保测试通过

---

## 2. 改造原则

### 2.1 自底向上顺序

```
存储层 (JSONStore) 
    ↓
模型层 (EmbeddingModel, ChatModel)
    ↓
接口层 (MemoryStore Protocol)
    ↓
业务层 (MemoryModule Facade, components)
    ↓
工作流层 (AgentWorkflow)
    ↓
API层 (FastAPI routes)
```

### 2.2 通用原则

- 所有 IO 操作（文件、网络）必须异步化
- 同步代码调用异步函数：使用 `asyncio.to_thread` 封装
- Protocol/接口定义与实现同步改造
- 保持串行执行逻辑不变

---

## 3. 各层改造详细设计

### 3.1 存储层 — `app/storage/json_store.py`

**现状**: 同步文件 IO（`open/read/write`）

**改造方案**:
```python
import aiofiles

class JSONStore:
    async def read(self) -> T: ...
    async def write(self, data: T) -> None: ...
    async def append(self, item: Any) -> None: ...
    async def update(self, key: str, value: Any) -> None: ...
```

**依赖**: `aiofiles>=24.1.0`

### 3.2 模型层 — `app/models/embedding.py`

**现状**: 同步 `encode` / `batch_encode`，无 async 版本

**改造方案**:
```python
import asyncio

class EmbeddingModel:
    async def encode(self, text: str) -> list[float]:
        return await asyncio.to_thread(self._sync_encode, text)
    
    async def batch_encode(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self._sync_batch_encode, texts)
    
    def _sync_encode(self, text: str) -> list[float]: ...
    def _sync_batch_encode(self, texts: list[str]) -> list[list[float]]: ...
```

**说明**: sentence-transformers 无原生 async，通过 `asyncio.to_thread` 封装到线程池，避免阻塞事件循环。

### 3.3 模型层 — `app/models/chat.py`

**现状**: 同步 `generate`，已有 `generate_stream` async

**改造方案**:
```python
class ChatModel:
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
                response = await client.chat.completions.create(...)
                return response.choices[0].message.content or ""
            except Exception as e:
                errors.append(f"{provider.provider.model}: {e}")
                continue
        raise RuntimeError(f"All LLM providers failed: {'; '.join(errors)}")
```

**说明**: 新增 `async generate` 方法，替换原同步方法。调用方全部改为 await。

### 3.4 接口层 — `app/memory/interfaces.py`

**现状**: Protocol 定义，同步方法签名

**改造方案**:
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

### 3.5 业务层 — `app/memory/components.py`

**现状**: EventStorage, FeedbackManager, MemoryBankEngine 全部同步

**改造方案**: 所有公开方法和内部调用存储/模型的方法均改为 async

关键变更:
```python
class EventStorage:
    async def append_event(self, event: MemoryEvent) -> str: ...
    async def read_events(self) -> list[dict]: ...
    async def write_events(self, events: list[dict]) -> None: ...

class FeedbackManager:
    async def update_feedback(self, event_id: str, feedback: FeedbackData) -> None: ...

class MemoryBankEngine:
    async def write(self, event: MemoryEvent) -> str: ...
    async def search(self, query: str, top_k: int = 10) -> list[SearchResult]: ...
    async def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str: ...
```

### 3.6 业务层 — `app/memory/stores/memory_bank_store.py`

**现状**: 同步方法调用 engine

**改造方案**:
```python
class MemoryBankStore:
    async def write(self, event: MemoryEvent) -> str:
        return await self._engine.write(event)
    
    async def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        return await self._engine.search(query, top_k)
    # ... 其他方法同理
```

### 3.7 Facade 层 — `app/memory/memory.py`

**现状**: 同步 `write`, `search`, `get_history`, `update_feedback`

**改造方案**:
```python
class MemoryModule:
    async def write(self, event: MemoryEvent) -> str:
        return await self._get_store(self._default_mode).write(event)
    
    async def search(
        self, query: str, mode: MemoryMode | None = None, top_k: int = 10
    ) -> list[SearchResult]:
        target_mode = mode or self._default_mode
        return await self._get_store(target_mode).search(query, top_k)
    # ... 其他方法同理
```

### 3.8 工作流层 — `app/agents/workflow.py`

**现状**: `run()` 同步，节点方法同步

**改造方案**:
```python
class AgentWorkflow:
    async def run(self, user_input: str) -> tuple[str, str | None]:
        state: AgentState = {...}
        for node_fn in self._nodes:
            updates = await node_fn(state)
            state.update(updates)
        ...

    async def _context_node(self, state: AgentState) -> dict:
        # 内部调用 memory_module.search 改为 await
        related_events = await self.memory_module.search(...)
        context = await self._call_llm_json_async(prompt)
        ...

    async def _call_llm_json_async(self, prompt: str) -> dict:
        """新增 async 版本"""
        if not self.memory_module.chat_model:
            raise RuntimeError("ChatModel not available")
        result = await self.memory_module.chat_model.generate(prompt)
        # ... JSON 解析逻辑
```

### 3.9 API 层 — `app/api/main.py`

**现状**: FastAPI routes 已使用 async def

**改造方案**: 调用方改为 await
```python
@app.post("/api/query")
async def query(request: QueryRequest, mm: MemoryModule = Depends(get_memory_module)) -> dict:
    workflow = AgentWorkflow(...)
    result, event_id = await workflow.run(request.query)  # 改为 await
    ...

@app.post("/api/feedback")
async def feedback(request: FeedbackRequest, mm: MemoryModule = Depends(get_memory_module)) -> dict:
    await mm.update_feedback(request.event_id, feedback)  # 改为 await
    ...

@app.get("/api/history")
async def history(limit: int = 10, mm: MemoryModule = Depends(get_memory_module)) -> dict:
    events = await mm.get_history(limit=limit)  # 改为 await
    ...
```

---

## 4. 依赖变更

### `pyproject.toml` 新增依赖

```toml
dependencies = [
    ...
    "aiofiles>=24.1.0",
]
```

### 开发依赖

```toml
[dependency-groups]
dev = [
    "pytest>=9.0.2",
    "pytest-asyncio>=0.25.0",  # 升级版本
]
```

---

## 5. 测试改造

### 5.1 pytest 配置

`pytest.ini` 新增:
```ini
[pytest]
asyncio_mode = auto
asyncio_default_fixture_loop_scope = function
```

### 5.2 测试函数改造

所有测试中的同步调用改为 async：
```python
# before
result = memory_module.search(query)

# after
result = await memory_module.search(query)
```

---

## 6. 实施顺序

### Phase 1: 基础设施异步化
1. 添加 `aiofiles` 依赖
2. `JSONStore` 改为 async
3. 验证基础测试通过

### Phase 2: 模型层异步化
4. `EmbeddingModel` 添加 async 方法
5. `ChatModel` 添加/替换为 async `generate`
6. 更新所有调用方

### Phase 3: 业务层异步化
7. `MemoryStore` Protocol 改为 async
8. `MemoryBankStore` 实现改为 async
9. `MemoryModule` Facade 改为 async
10. `components.py` 所有类方法改为 async

### Phase 4: 工作流异步化
11. `AgentWorkflow` 改为 async
12. 更新 API 层调用

### Phase 5: 收尾
13. 更新所有测试为 async
14. 运行完整测试套件
15. ruff/ty 检查

---

## 7. 风险与缓解

| 风险 | 级别 | 缓解措施 |
|------|------|----------|
| `sentence-transformers` GIL 竞争 | 低 | embedding 计算时间短，影响可接受；后续可考虑进程池 |
| `aiofiles` 异常处理 | 低 | 明确异常传播，测试覆盖 |
| 改造过程中测试失败 | 中 | 逐步推进，每阶段验证 |
| Protocol 异步化后类型检查 | 低 | ty 已支持 async Protocol |

---

## 8. 验收标准

- [ ] 所有非 vendor 模块的方法签名包含 `async def`
- [ ] 无同步 IO 调用（无 `open(...).read/write` 在 async 函数中）
- [ ] `pytest` 异步测试全部通过
- [ ] `uv run ruff check` 无错误
- [ ] `uv run ty check` 无错误
