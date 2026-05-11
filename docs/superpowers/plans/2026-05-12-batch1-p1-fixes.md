# 第一批：P1 功能缺陷 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 subagent-driven-development（推荐）或 executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 修复 4 项运行时功能缺陷：SSE 伪流式、FAISS 阻塞事件循环、update_feedback 并发竞争、feedback 超上限。

**架构：** 四项均为独立单文件改动，无交叉依赖，可并行或串行执行。

**技术栈：** Python 3.14, asyncio, FastAPI, FAISS, pytest

**设计规格：** `docs/superpowers/specs/2026-05-12-refactoring-plan.md` 第 1 节

---

### 任务 1：SSE 流式改造（`run_stream` 改 AsyncGenerator）

**文件：**
- 修改：`app/agents/workflow.py` — `run_stream` 签名及实现
- 修改：`app/api/stream.py` — 调用方改为 `async for`
- 测试：`tests/test_sse_stream.py`（新建）

**说明：**
当前 `run_stream()` 先完成全部阶段计算再批量返回 `list[dict]`，非真流式。改为 `AsyncGenerator`，每阶段完成后 `yield`。`stream.py` 中 `event_generator()` 改为 `async for` 消费。

`run_with_stages()` 不受影响（保持同步返回）。

**设计细节：**
- `run_stream()` 签名：`async def run_stream(...) -> AsyncGenerator[dict, None]`
- 阶段顺序不变：context → task → strategy → execution
- 异常时 yield `{"event": "error", "data": {"code": "...", "message": "..."}}` 然后 return
- shortcut 路径也 yield 事件
- 不修改 `AgentWorkflow.__init__`、不修改内存模块

- [ ] **步骤 1：编写测试**

```python
# tests/test_sse_stream.py
"""SSE 流式端点测试。mock LLM 以避免真实调用。"""

import pytest
from unittest.mock import AsyncMock, patch

from app.agents.workflow import AgentWorkflow
from app.memory.types import MemoryMode


@pytest.fixture
def workflow():
    """mock MemoryModule + ChatModel 的 AgentWorkflow 实例。"""
    with (
        patch("app.agents.workflow.MemoryModule") as mock_mm,
        patch("app.agents.workflow.get_chat_model") as mock_get,
    ):
        mock_chat = AsyncMock()
        mock_chat.generate.return_value = '{"key": "value"}'
        mock_get.return_value = mock_chat
        mock_mm_instance = AsyncMock()
        mock_mm_instance.search.return_value = []
        mock_mm_instance.get_history.return_value = []
        mock_mm.return_value = mock_mm_instance
        wf = AgentWorkflow(memory_mode=MemoryMode.MEMORY_BANK)
        yield wf


@pytest.mark.asyncio
async def test_run_stream_yields_context_done_first(workflow):
    """run_stream 首个事件应为 context_done（shortcut 除外）。"""
    events = []
    async for evt in workflow.run_stream("明天开会", session_id=None):
        events.append(evt)
    assert len(events) > 0
    assert events[0]["event"] == "stage_start"
    assert events[0]["data"]["stage"] == "context"


@pytest.mark.asyncio
async def test_run_stream_ends_with_done(workflow):
    """run_stream 最后事件应为 done。"""
    events = []
    async for evt in workflow.run_stream("明天开会"):
        events.append(evt)
    assert events[-1]["event"] == "done"


@pytest.mark.asyncio
async def test_run_stream_yields_all_stages(workflow):
    """run_stream 应产出 context/task/strategy/execution 四阶段事件。"""
    stages = set()
    async for evt in workflow.run_stream("明天开会"):
        if evt["event"] == "stage_start":
            stages.add(evt["data"]["stage"])
    assert stages == {"context", "task", "strategy", "execution"}


@pytest.mark.asyncio
async def test_run_stream_shortcut_still_works(workflow):
    """快捷指令路径（如静音）不应走完整流水线。"""
    events = []
    async for evt in workflow.run_stream("静音"):
        events.append(evt)
    # shortcut 路径直接 execution → done，不该有 stage_start
    stage_starts = [e for e in events if e["event"] == "stage_start"]
    assert len(stage_starts) == 0


@pytest.mark.asyncio
async def test_run_stream_error_yields_error_event(workflow):
    """LLM 调用失败时发出 error 事件。"""
    workflow._call_llm_json = AsyncMock(side_effect=RuntimeError("LLM down"))
    events = []
    async for evt in workflow.run_stream("明天开会"):
        events.append(evt)
    assert events[-1]["event"] == "error"


@pytest.mark.asyncio
async def test_run_with_stages_unchanged(workflow):
    """run_with_stages 仍返回 (str, str|None, WorkflowStages)。"""
    from app.agents.state import WorkflowStages
    result, event_id, stages = await workflow.run_with_stages("明天开会")
    assert isinstance(result, str)
    assert isinstance(stages, WorkflowStages)
```

- [ ] **步骤 2：运行测试验证失败**

运行：`uv run pytest tests/test_sse_stream.py -v`
预期：MODULE_NOT_FOUND 或导入错误（测试文件新建）

- [ ] **步骤 3：修改 `workflow.py` — `run_stream()` 改 AsyncGenerator**

`run_stream` 方法改为 async generator。核心改动：

```python
# app/agents/workflow.py
from collections.abc import AsyncGenerator

# 在 AgentWorkflow 类中，将 run_stream 改为：

async def run_stream(
    self,
    user_input: str,
    driving_context: dict | None = None,
    session_id: str | None = None,
) -> AsyncGenerator[dict, None]:
    """SSE 流式方法，逐阶段 yield 事件。

    每个阶段完成后立即 yield，不等待全部阶段结束。
    设计说明见 run_with_stages。
    """
    stages = WorkflowStages()
    state: AgentState = {
        "original_query": user_input,
        "context": {},
        "task": None,
        "decision": None,
        "result": None,
        "event_id": None,
        "driving_context": driving_context,
        "stages": stages,
        "session_id": session_id,
    }

    # --- 快捷指令检查 ---
    shortcut_decision = self._shortcuts.resolve(user_input)
    if shortcut_decision:
        if driving_context:
            shortcut_decision, _modifications = postprocess_decision(
                shortcut_decision, driving_context
            )
        state["decision"] = shortcut_decision
        try:
            exec_result = await self._execution_node(state)
            state.update(exec_result)
            done_data = self._build_done_data(state, session_id)
            yield {"event": "done", "data": done_data}
        except Exception as e:
            yield {"event": "error", "data": {"code": "INTERNAL", "message": str(e)}}
        if session_id:
            self._conversations.add_turn(
                session_id, user_input, shortcut_decision,
                state.get("result") or "",
            )
        return

    # 阶段 1: Context
    yield {"event": "stage_start", "data": {"stage": "context"}}
    try:
        updates = await self._context_node(state)
        state.update(updates)
        yield {"event": "context_done", "data": {"context": state["context"]}}
    except Exception as e:
        yield {"event": "error", "data": {"code": "CONTEXT_FAILED", "message": str(e)}}
        return

    # 阶段 2: Task
    yield {"event": "stage_start", "data": {"stage": "task"}}
    try:
        updates = await self._task_node(state)
        state.update(updates)
        yield {"event": "task_done", "data": {"tasks": state.get("task") or {}}}
    except Exception as e:
        yield {"event": "error", "data": {"code": "TASK_FAILED", "message": str(e)}}
        return

    # 阶段 3: Strategy
    yield {"event": "stage_start", "data": {"stage": "strategy"}}
    try:
        updates = await self._strategy_node(state)
        state.update(updates)
        decision = state.get("decision") or {}
        yield {
            "event": "decision",
            "data": {"should_remind": decision.get("should_remind")},
        }
    except Exception as e:
        yield {"event": "error", "data": {"code": "STRATEGY_FAILED", "message": str(e)}}
        return

    # 阶段 4: Execution
    yield {"event": "stage_start", "data": {"stage": "execution"}}
    try:
        updates = await self._execution_node(state)
        state.update(updates)
        done_data = self._build_done_data(state, session_id)
        yield {"event": "done", "data": done_data}
    except Exception as e:
        yield {"event": "error", "data": {"code": "EXECUTION_FAILED", "message": str(e)}}
        return

    if session_id:
        self._conversations.add_turn(
            session_id, user_input,
            state.get("decision") or {},
            state.get("result") or "",
        )
```

需要加一个新辅助方法：

```python
@staticmethod
def _build_done_data(state: AgentState, session_id: str | None) -> dict:
    """构建 done 事件 data 字典。"""
    done_data: dict[str, object] = {
        "event_id": state.get("event_id"),
        "session_id": session_id,
    }
    pending_id = state.get("pending_reminder_id")
    if pending_id:
        done_data["status"] = "pending"
        done_data["pending_reminder_id"] = pending_id
    elif state.get("result") and "取消" in str(state.get("result")):
        done_data["status"] = "suppressed"
        done_data["reason"] = state.get("result")
    else:
        done_data["status"] = "delivered"
        done_data["result"] = state.get("output_content")
    return done_data
```

- [ ] **步骤 4：运行测试验证通过**

运行：`uv run pytest tests/test_sse_stream.py -v`
预期：5 passed

- [ ] **步骤 5：修改 `stream.py` — 调用方改为 `async for`**

```python
# app/api/stream.py，替换现有 event_generator 逻辑：

@router.post("/query/stream")
async def query_stream(req: ProcessQueryRequest) -> StreamingResponse:
    """处理用户查询并以 SSE 流式返回各阶段结果。"""
    mm = get_memory_module()
    workflow = AgentWorkflow(
        data_dir=DATA_DIR,
        memory_mode=MemoryMode(req.memory_mode),
        memory_module=mm,
        current_user=req.current_user,
    )

    driving_context = req.context

    async def event_generator() -> AsyncGenerator[str]:
        try:
            async for event in workflow.run_stream(
                req.query,
                driving_context,
                session_id=req.session_id,
            ):
                data_str = json.dumps(event["data"], ensure_ascii=False)
                yield f"event: {event['event']}\ndata: {data_str}\n\n"
        except Exception as e:
            logger.exception("Stream error")
            err = json.dumps({"code": "INTERNAL", "message": str(e)})
            yield f"event: error\ndata: {err}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

- [ ] **步骤 6：运行完整测试套件**

运行：`uv run pytest tests/ -v`
预期：355+ passed（新增 SSE 测试）

- [ ] **步骤 7：lint / type check / commit**

```bash
uv run ruff check --fix && uv run ruff format
uv run ty check
git add app/agents/workflow.py app/api/stream.py tests/test_sse_stream.py
git commit -m "fix: convert SSE run_stream to true AsyncGenerator for per-stage streaming"
```

---

### 任务 2：FAISS `load()` 非阻塞

**文件：**
- 修改：`app/memory/memory_bank/index.py` — `load()` 中同步 I/O 转 `run_in_executor`
- 测试：`tests/stores/test_index_recovery.py` — 新增加载性能测试

**说明：**
`faiss.read_index()`、`json.loads()`、`shutil.copy()`、`Path.read_text()` 等同步 I/O 在 `async load()` 中直接调用。包装到 `run_in_executor` 避免阻塞事件循环。

至少包装以下操作：`faiss.read_index`、`mp.read_text`、`ep.read_text`、`shutil.copy`、`ip.unlink`、`mp.unlink`、`ep.unlink`。

- [ ] **步骤 1：编写测试**

```python
# 在 tests/stores/test_index_recovery.py 中追加：

@pytest.mark.asyncio
async def test_index_load_does_not_block_event_loop(tmp_path):
    """load() 中的同步 I/O 不应阻塞事件循环。"""
    import asyncio
    from app.memory.memory_bank.index import FaissIndex

    # 验证 load() 执行期间其他协程仍可运行
    idx = FaissIndex(tmp_path)

    async def canary():
        await asyncio.sleep(0.01)
        return "alive"

    # 同时运行 load 和 canary（load 为空目录应快速返回）
    load_task = asyncio.create_task(idx.load())
    canary_task = asyncio.create_task(canary())
    done, _ = await asyncio.wait(
        [load_task, canary_task],
        return_when=asyncio.FIRST_COMPLETED,
    )
    # canary 应能完成——若 load 阻塞事件循环则 canary 被卡住
    assert any(t == canary_task and t.done() for t in done)
```

- [ ] **步骤 2：运行测试验证失败或跳过**

运行：`uv run pytest tests/stores/test_index_recovery.py::test_index_load_does_not_block_event_loop -v`
预期：PASS（当前实现也可能通过，因为空索引 load 很快——测试仅作回归）

- [ ] **步骤 3：修改 `index.py` — 同步 I/O 用 `run_in_executor`**

`FaissIndex.load()` 中所有同步文件操作包装为线程池调用。核心模式：

```python
import asyncio
from functools import partial

# 在类内加：
async def _run_sync(self, func, *args, **kwargs):
    """在默认线程池中执行同步函数。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))
```

然后在 `load()` 中：

```python
# 包装 faiss.read_index
idx_raw = await self._run_sync(faiss.read_index, str(ip))

# 包装 json.loads + read_text
raw_meta = await self._run_sync(mp.read_text)
meta = _validate_metadata_structure(json.loads(raw_meta))

# 包装 shutil.copy
await self._run_sync(shutil.copy, str(ip), str(bak_path))

# 包装 unlink
await self._run_sync(ip.unlink, missing_ok=True)
```

同样包装 `save()` 中的 `faiss.write_index`、`write_text`。

- [ ] **步骤 4：运行测试验证通过**

运行：`uv run pytest tests/stores/test_index_recovery.py -v`
预期：全部 PASS

- [ ] **步骤 5：lint / type check / commit**

```bash
uv run ruff check --fix && uv run ruff format
uv run ty check
git add app/memory/memory_bank/index.py
git commit -m "fix: wrap FAISS synchronous I/O in run_in_executor to avoid blocking event loop"
```

---

### 任务 3：`update_feedback` 并发保护

**文件：**
- 修改：`app/memory/memory_bank/lifecycle.py` — 加 `_feedback_lock`
- 测试：`tests/stores/test_forgetting.py` — 新增并发测试

**说明：**
`update_feedback()` 直接 mutate `get_metadata_by_id(fid)` 返回的 dict。加 `asyncio.Lock` 保护 `memory_strength` + `last_recall_date` 的读-改-写序列。

- [ ] **步骤 1：编写测试**

```python
# 在 tests/stores/test_forgetting.py 中追加：

@pytest.mark.asyncio
async def test_update_feedback_concurrent_safe(tmp_path):
    """并发 update_feedback 不应导致 memory_strength 不一致。"""
    import asyncio
    from app.memory.memory_bank.config import MemoryBankConfig
    from app.memory.memory_bank.forget import ForgettingCurve
    from app.memory.memory_bank.index import FaissIndex
    from app.memory.memory_bank.lifecycle import MemoryLifecycle
    from app.memory.schemas import FeedbackData

    config = MemoryBankConfig(max_memory_strength=10)
    idx = FaissIndex(tmp_path)
    await idx.load()

    # mock embedding
    class FakeEmbeddingClient:
        async def encode(self, text): return [0.1] * 1536
        async def encode_batch(self, texts): return [[0.1] * 1536 for _ in texts]

    lifecycle = MemoryLifecycle(
        idx, FakeEmbeddingClient(), ForgettingCurve(config), None, config,
    )

    # 写一条事件
    from app.memory.schemas import MemoryEvent
    event = MemoryEvent(content="test", type="reminder")
    fid = await lifecycle.write(event)

    # 并发 10 次 accept
    async def concurrent_accept(eid):
        fb = FeedbackData(action="accept", type="reminder")
        await lifecycle.update_feedback(eid, fb)

    await asyncio.gather(*[concurrent_accept(fid) for _ in range(10)])

    # memory_strength 应为 1 + 2*10 = 21，但上限 10
    m = idx.get_metadata_by_id(int(fid))
    assert m is not None
    final = float(m.get("memory_strength", 0))
    assert final == 10.0, f"expected 10.0, got {final}"
```

- [ ] **步骤 2：运行测试验证基线**

运行：`uv run pytest tests/stores/test_forgetting.py::test_update_feedback_concurrent_safe -v`
预期：PASS。（asyncio 单线程下 read-modify-write 无 `await` 点，当前无竞争。此测试为回归防护——锁加后语义更安全，防未来引入 `await` 破坏原子性。）

- [ ] **步骤 3：修改 `lifecycle.py` — 加 `_feedback_lock`**

```python
# 在 MemoryLifecycle.__init__ 中：
self._feedback_lock = asyncio.Lock()

# update_feedback 方法加锁保护：
async def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
    async with self._feedback_lock:
        # ... 原有实现 ...
```

- [ ] **步骤 4：运行测试验证通过**

运行：`uv run pytest tests/stores/test_forgetting.py::test_update_feedback_concurrent_safe -v`
预期：PASS

- [ ] **步骤 5：lint / type check / commit**

```bash
uv run ruff check --fix && uv run ruff format
uv run ty check
git add app/memory/memory_bank/lifecycle.py
git commit -m "fix: add asyncio.Lock to update_feedback for concurrent safety"
```

---

### 任务 4：feedback 受 `max_memory_strength` 上限约束

**文件：**
- 修改：`app/memory/memory_bank/lifecycle.py` — `update_feedback` 加 `min(_, config.max_memory_strength)`
- 测试：同任务 3 的测试（已覆盖）

**说明：**
`update_feedback()` 中 `old_strength + 2.0` 不做上限检查。检索管道的 `_update_memory_strengths` 已有 `min(_, max_memory_strength)` 保护，此路径遗漏。

- [ ] **步骤 1：编写测试**

```python
# 在 tests/stores/test_forgetting.py 中追加：

@pytest.mark.asyncio
async def test_update_feedback_respects_max_strength(tmp_path):
    """update_feedback accept 不应超过 max_memory_strength。"""
    from app.memory.memory_bank.config import MemoryBankConfig
    from app.memory.memory_bank.forget import ForgettingCurve
    from app.memory.memory_bank.index import FaissIndex
    from app.memory.memory_bank.lifecycle import MemoryLifecycle
    from app.memory.schemas import FeedbackData, MemoryEvent

    config = MemoryBankConfig(max_memory_strength=5)  # 上限 5
    idx = FaissIndex(tmp_path)
    await idx.load()

    class FakeEmbeddingClient:
        async def encode(self, text): return [0.1] * 1536
        async def encode_batch(self, texts): return [[0.1] * 1536 for _ in texts]

    lifecycle = MemoryLifecycle(
        idx, FakeEmbeddingClient(), ForgettingCurve(config), None, config,
    )

    event = MemoryEvent(content="test", type="reminder")
    fid = await lifecycle.write(event)

    # 3 次 accept → +6 → 上限 5
    for _ in range(3):
        fb = FeedbackData(action="accept", type="reminder")
        await lifecycle.update_feedback(fid, fb)

    m = idx.get_metadata_by_id(int(fid))
    assert m is not None
    assert float(m.get("memory_strength", 0)) == 5.0


@pytest.mark.asyncio
async def test_update_feedback_ignore_never_below_one(tmp_path):
    """update_feedback ignore 不应低于 1.0。"""
    from app.memory.memory_bank.config import MemoryBankConfig
    from app.memory.memory_bank.forget import ForgettingCurve
    from app.memory.memory_bank.index import FaissIndex
    from app.memory.memory_bank.lifecycle import MemoryLifecycle
    from app.memory.schemas import FeedbackData, MemoryEvent

    config = MemoryBankConfig(max_memory_strength=10)
    idx = FaissIndex(tmp_path)
    await idx.load()

    class FakeEmbeddingClient:
        async def encode(self, text): return [0.1] * 1536
        async def encode_batch(self, texts): return [[0.1] * 1536 for _ in texts]

    lifecycle = MemoryLifecycle(
        idx, FakeEmbeddingClient(), ForgettingCurve(config), None, config,
    )

    event = MemoryEvent(content="test", type="reminder")
    fid = await lifecycle.write(event)

    # 多次 ignore → 不应低于 1
    for _ in range(5):
        fb = FeedbackData(action="ignore", type="reminder")
        await lifecycle.update_feedback(fid, fb)

    m = idx.get_metadata_by_id(int(fid))
    assert m is not None
    assert float(m.get("memory_strength", 0)) == 1.0
```

- [ ] **步骤 2：运行测试确认当前行为**

运行：`uv run pytest tests/stores/test_forgetting.py::test_update_feedback_respects_max_strength -v`
预期：FAIL（当前无上限，值为 7）

- [ ] **步骤 3：修改 `lifecycle.py` — accept 路径加 `min`**

```python
# update_feedback 中 accept 分支：
if feedback.action == "accept":
    m["memory_strength"] = min(
        old_strength + 2.0,
        float(self._config.max_memory_strength),
    )
```

- [ ] **步骤 4：运行测试验证通过**

运行：`uv run pytest tests/stores/test_forgetting.py::test_update_feedback_respects_max_strength tests/stores/test_forgetting.py::test_update_feedback_ignore_never_below_one -v`
预期：PASS

- [ ] **步骤 5：运行全部测试确认无回归**

运行：`uv run pytest tests/ -v`
预期：355+ passed

- [ ] **步骤 6：lint / type check / commit**

```bash
uv run ruff check --fix && uv run ruff format
uv run ty check
git add app/memory/memory_bank/lifecycle.py
git commit -m "fix: cap update_feedback accept at max_memory_strength, floor ignore at 1.0"
```

---

## 自检清单

- [ ] 规格覆盖：batch 1 全部 4 项都有对应任务
- [ ] 占位符：无 TODO / TBD
- [ ] 类型一致：函数签名与方法名在任务间一致
