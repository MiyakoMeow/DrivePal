# WebUI + REST API 优化实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 清理 GraphQL 迁移残留、移除 API 层 MemoryMode 暴露、补全 REST 边界校验、修复前端数据往返、对接 SSE 流式、反馈改 append-only JSONL。

**架构：** 六项优化按依赖分三层。第一层（O1+O2）清理残留，无依赖可并行。第二层（O3+O4）依赖 O2 完成。第三层（O5+O6）依赖前置全部完成。

**技术栈：** Python 3.14 + FastAPI + Pydantic + vanilla JS + JSONL

---

## 文件结构

### 新建文件

| 文件 | 职责 |
|------|------|
| `app/storage/feedback_log.py` | append-only 反馈日志，聚合权重计算 |

### 修改文件

| 文件 | 变更 |
|------|------|
| `webui/index.html` | 删 GraphQL 链接、删记忆模式区块 |
| `webui/app.js` | 删 memoryMode、修复 incidents、改 SSE |
| `app/api/AGENTS.md` | 重写为 REST API 文档 |
| `app/schemas/query.py` | context 强类型、删 memory_mode |
| `app/api/schemas.py` | 删 memory_mode |
| `app/api/routes/query.py` | 硬编码 MemoryMode |
| `app/api/routes/feedback.py` | 改用 feedback_log 聚合权重 |
| `app/api/routes/data.py` | 删 memory_mode 参数 |
| `app/api/stream.py` | 硬编码 MemoryMode |
| `app/api/main.py` | CORS 注释标注 |
| `app/agents/workflow.py` | 删 memory_mode 参数、硬编码 |
| `tests/api/test_rest.py` | 更新测试 |
| `tests/agents/test_sse_stream.py` | 更新测试 |
| `tests/storage/test_storage.py` | 更新测试 |

---

## 第一层：清理

### 任务 1：删除 GraphQL 残留

**文件：**
- 修改：`webui/index.html:13`
- 修改：`app/api/AGENTS.md`

- [ ] **步骤 1：删死链接**

`webui/index.html` 第 13 行 `<a href="/graphql">` 删除。

```html
<!-- 删除这行 -->
<a href="/graphql" target="_blank">GraphQL Playground</a>
```

- [ ] **步骤 2：重写 app/api/AGENTS.md**

将全文替换为描述当前 REST API 的文档。内容需覆盖：
- 所有端点（方法、路径、用途）
- 请求/响应 schema（引用 `app/api/schemas.py` 中的 Pydantic model 名）
- SSE 流式端点说明
- 错误处理（`safe_memory_call`、路由级异常捕获）
- 服务入口与生命周期（从 `app/api/main.py`）
- CORS 配置（当前 `allow_origins=["*"]`，开发用）
- 反馈学习机制（reminder_weights → preference_hint → JointDecision prompt）

- [ ] **步骤 3：清 __pycache__**

```bash
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
```

- [ ] **步骤 4：Commit**

```bash
git add webui/index.html app/api/AGENTS.md
git commit -m "chore: remove GraphQL remnants and rewrite API docs"
```

---

### 任务 2：移除 API 层 MemoryMode 暴露

**文件：**
- 修改：`app/schemas/query.py`
- 修改：`app/api/schemas.py`
- 修改：`app/api/routes/query.py`
- 修改：`app/api/routes/feedback.py`
- 修改：`app/api/routes/data.py`
- 修改：`app/api/stream.py`
- 修改：`app/agents/workflow.py`（`__init__` 签名）
- 修改：`webui/index.html`
- 修改：`webui/app.js`
- 修改：`tests/api/test_rest.py`
- 修改：`tests/agents/test_sse_stream.py`

**原则：** 保留 `app/memory/types.py` 中 `MemoryMode` 枚举定义（内部模块大量引用）。仅删除 API 边界的 `memory_mode` 参数。`AgentWorkflow.__init__` 删 `memory_mode` 参数，内部硬编码 `MemoryMode.MEMORY_BANK`。

- [ ] **步骤 1：更新 `app/schemas/query.py`**

删除 `memory_mode` 字段和 `MemoryMode` import：

```python
"""SSE 查询端点输入/输出 schema."""

from __future__ import annotations

from pydantic import BaseModel


class ProcessQueryRequest(BaseModel):
    """POST /api/query 和 POST /api/query/stream 请求体."""

    query: str
    context: dict | None = None
    current_user: str = "default"
    session_id: str | None = None


class ProcessQueryResult(BaseModel):
    """SSE 'done' 事件 data schema。

    注意：当前 SSE 端点（stream.py）使用 run_stream() 返回的 list[dict]
    直接构造事件，未用此 schema 校验。此 schema 作为文档化的契约参考。
    """

    status: str = "delivered"  # "delivered" | "pending" | "suppressed"
    event_id: str | None = None
    session_id: str | None = None
    result: dict | None = None  # MultiFormatContent.model_dump()
    pending_reminder_id: str | None = None
    trigger_text: str | None = None
    reason: str | None = None
    cancelled: bool | None = None  # cancel_last action result
```

- [ ] **步骤 2：更新 `app/api/schemas.py`**

删除 `FeedbackRequest.memory_mode` 字段和 `MemoryMode` import：

```python
from typing import Literal

from pydantic import BaseModel

from app.schemas.context import DrivingContext
```

`FeedbackRequest` 改为：

```python
class FeedbackRequest(BaseModel):
    """POST /api/feedback 请求."""

    event_id: str
    action: Literal["accept", "ignore"]
    modified_content: str | None = None
    current_user: str = "default"
```

- [ ] **步骤 3：更新 `app/agents/workflow.py`**

`__init__` 签名删除 `memory_mode` 参数，硬编码：

```python
def __init__(
    self,
    data_dir: Path = Path("data"),
    memory_module: MemoryModule | None = None,
    current_user: str = "default",
) -> None:
    """初始化工作流实例."""
    self.data_dir = data_dir
    self._memory_mode = MemoryMode.MEMORY_BANK
    self.current_user = current_user
    # ... 其余不变
```

- [ ] **步骤 4：更新 `app/api/routes/query.py`**

删除 `MemoryMode` import 和 `req.memory_mode` 使用：

```python
from app.agents.workflow import AgentWorkflow, ChatModelUnavailableError
from app.api.schemas import ProcessQueryResponse
from app.config import DATA_DIR
from app.memory.singleton import get_memory_module
from app.schemas.query import ProcessQueryRequest
```

构造 workflow 时删 `memory_mode` 参数：

```python
workflow = AgentWorkflow(
    data_dir=DATA_DIR,
    memory_module=mm,
    current_user=req.current_user,
)
```

- [ ] **步骤 5：更新 `app/api/routes/feedback.py`**

删 `MemoryMode` import 和 `req.memory_mode` 使用。所有 `mode=MemoryMode(req.memory_mode)` 改为 `mode=MemoryMode.MEMORY_BANK`：

```python
from app.api.errors import safe_memory_call
from app.api.schemas import FeedbackRequest, FeedbackResponse
from app.config import user_data_dir
from app.memory.schemas import FeedbackData
from app.memory.singleton import get_memory_module
from app.memory.types import MemoryMode
from app.storage.toml_store import TOMLStore
```

路由中 `mode = MemoryMode(req.memory_mode)` 改为 `mode = MemoryMode.MEMORY_BANK`。

- [ ] **步骤 6：更新 `app/api/routes/data.py`**

`get_history()` 删 `memory_mode` 查询参数，硬编码：

```python
@router.get("/history", response_model=list[MemoryEventResponse])
async def get_history(
    limit: int = 10,
    current_user: str = "default",
) -> list[MemoryEventResponse]:
    """查询历史记忆事件."""
    mm = get_memory_module()
    events = await mm.get_history(limit=limit, mode=MemoryMode.MEMORY_BANK, user_id=current_user)
    return [
        MemoryEventResponse(
            id=e.id,
            content=e.content,
            type=e.type,
            description=e.description,
            created_at=e.created_at,
        )
        for e in events
    ]
```

同时删去原来的 `MemoryMode(memory_mode)` 解析逻辑和 422 异常。

- [ ] **步骤 7：更新 `app/api/stream.py`**

删 `req.memory_mode` 使用：

```python
workflow = AgentWorkflow(
    data_dir=DATA_DIR,
    memory_module=mm,
    current_user=req.current_user,
)
```

- [ ] **步骤 8：更新前端**

`webui/index.html` 删除整个"记忆模式"区块（`<div>` 含 `section-title` "记忆模式" 及其子元素 `memory-row`）。

`webui/app.js`：
- 删 `sendQuery()` 中 `const memoryMode = ...` 和 `body.memory_mode`
- 删 `loadHistory()` 中 `const mode = ...` 和 URL 中 `memory_mode=${mode}`，改为硬编码 `/api/history?limit=10`

- [ ] **步骤 9：更新测试**

`tests/api/test_rest.py`：
- `test_process_query_without_context`：删 json 中 `"memory_mode": "memory_bank"`
- `test_process_query_with_context`：同上
- `test_feedback_success_updates_strategy_weight`：删 json 中 `"memory_mode"`（已无此字段）

`tests/agents/test_sse_stream.py`：
- `workflow` fixture：删 `memory_mode=MemoryMode.MEMORY_BANK` 参数（现在是默认值）

- [ ] **步骤 10：运行 lint + 测试**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
uv run pytest tests/ -v -x --timeout=60
```

预期：全部通过。若有 ty 类型错误（因 workflow 签名变更），修调用方。

- [ ] **步骤 11：Commit**

```bash
git add -A
git commit -m "refactor: remove memory_mode from API boundary"
```

---

## 第二层：校验与修复

### 任务 3：REST 边界 context 强类型校验

**文件：**
- 修改：`app/schemas/query.py`

- [ ] **步骤 1：编写失败测试**

在 `tests/schemas/test_context_schemas.py` 末尾追加：

```python
def test_process_query_request_validates_context() -> None:
    """ProcessQueryRequest.context 接受 DrivingContext 结构."""
    from app.schemas.query import ProcessQueryRequest

    req = ProcessQueryRequest(
        query="测试",
        context={
            "driver": {"emotion": "calm"},
            "scenario": "highway",
        },
    )
    assert req.context is not None
    assert req.context.scenario == "highway"


def test_process_query_request_invalid_context_raises() -> None:
    """ProcessQueryRequest.context 拒绝非法字段值."""
    from pydantic import ValidationError

    from app.schemas.query import ProcessQueryRequest

    with pytest.raises(ValidationError):
        ProcessQueryRequest(
            query="测试",
            context={"scenario": "invalid_scenario"},
        )
```

- [ ] **步骤 2：运行测试验证失败**

```bash
uv run pytest tests/schemas/test_context_schemas.py::test_process_query_request_validates_context tests/schemas/test_context_schemas.py::test_process_query_request_invalid_context_raises -v
```

预期：FAIL（`context: dict | None` 不校验内部结构）

- [ ] **步骤 3：实现强类型**

`app/schemas/query.py`：

```python
"""查询端点输入/输出 schema."""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.context import DrivingContext


class ProcessQueryRequest(BaseModel):
    """POST /api/query 和 POST /api/query/stream 请求体."""

    query: str
    context: DrivingContext | None = None
    current_user: str = "default"
    session_id: str | None = None
```

- [ ] **步骤 4：运行测试验证通过**

```bash
uv run pytest tests/schemas/test_context_schemas.py -v
```

预期：全部 PASS。

- [ ] **步骤 5：运行全量测试**

```bash
uv run pytest tests/ -v -x --timeout=60
```

若 API 测试因 context 类型变更失败（如 `test_process_query_with_context` 传 dict 但现需 DrivingContext），检查 Pydantic 是否自动解析。`DrivingContext` 所有子模型均有默认值，`model_validate` 应自动填充。

- [ ] **步骤 6：Commit**

```bash
git add app/schemas/query.py tests/schemas/test_context_schemas.py
git commit -m "feat: validate context as DrivingContext at REST boundary"
```

---

### 任务 4：修复 incidents 往返断裂

**文件：**
- 修改：`webui/app.js`

- [ ] **步骤 1：修复 `getContextInput()`**

L50 `if (incidents) traffic.incidents = [incidents];` 改为：

```javascript
if (incidents) traffic.incidents = incidents.split(',').map(s => s.trim()).filter(Boolean);
```

- [ ] **步骤 2：修复 `fillForm()`**

L85 `document.getElementById('ctx-incidents').value = t.incidents || '';` 改为：

```javascript
document.getElementById('ctx-incidents').value = Array.isArray(t.incidents) ? t.incidents.join(', ') : (t.incidents || '');
```

- [ ] **步骤 3：手动验证**

启动服务，在 webui 中输入事故信息（如"追尾, 施工"），保存为预设，加载预设，确认回填正确。

- [ ] **步骤 4：Commit**

```bash
git add webui/app.js
git commit -m "fix: incidents array round-trip between form and preset"
```

---

## 第三层：架构优化

### 任务 5：前端对接 SSE 流式

**文件：**
- 修改：`webui/app.js`

- [ ] **步骤 1：重写 `sendQuery()` 为 SSE**

思路：`sendQuery()` 改用 `fetch('/api/query/stream', ...)` + `ReadableStream` 逐行解析 SSE 事件。逐阶段填充 stage panel。`currentEventId` 从 `done` 事件获取。

接口（替换 `sendQuery` 函数整体）：

```javascript
async function sendQuery() {
    const query = document.getElementById('queryInput').value.trim();
    if (!query) return;

    const context = getContextInput();

    setLoading(true);
    document.getElementById('feedbackRow').style.display = 'none';
    ['context', 'task', 'decision', 'execution'].forEach(s => {
        document.getElementById(`stage-${s}-body`).innerHTML = '<span class="empty-hint">处理中...</span>';
    });

    try {
        const body = { query };
        if (context) body.context = context;

        const resp = await fetch('/api/query/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${resp.status}`);
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            let currentEvent = '';
            for (const line of lines) {
                if (line.startsWith('event: ')) {
                    currentEvent = line.slice(7).trim();
                } else if (line.startsWith('data: ') && currentEvent) {
                    const data = JSON.parse(line.slice(6));
                    handleSSEEvent(currentEvent, data);
                    currentEvent = '';
                }
            }
        }
        loadHistory();
    } catch (e) {
        ['context', 'task', 'decision', 'execution'].forEach(s => {
            const el = document.getElementById(`stage-${s}-body`);
            el.innerHTML = '<span class="error">Error: ' + escapeHtml(e.message) + '</span>';
        });
    } finally {
        setLoading(false);
    }
}
```

- [ ] **步骤 2：新增 `handleSSEEvent()` 函数**

在 `sendQuery()` 前插入：

```javascript
function handleSSEEvent(event, data) {
    switch (event) {
        case 'stage_start':
            document.getElementById(`stage-${data.stage}-body`).innerHTML =
                '<span class="empty-hint">处理中...</span>';
            break;
        case 'context_done':
            document.getElementById('stage-context-body').textContent = formatJson(data.context);
            break;
        case 'decision':
            document.getElementById('stage-decision-body').textContent = formatJson(data);
            break;
        case 'done':
            if (data.event_id) {
                currentEventId = data.event_id;
                document.getElementById('feedbackRow').style.display = 'flex';
            }
            if (data.result) {
                document.getElementById('stage-execution-body').textContent = formatJson(data.result);
            } else if (data.reason) {
                document.getElementById('stage-execution-body').textContent = data.reason;
            }
            break;
        case 'error':
            ['context', 'task', 'decision', 'execution'].forEach(s => {
                const el = document.getElementById(`stage-${s}-body`);
                if (el.querySelector('.empty-hint')) {
                    el.innerHTML = '<span class="error">' + escapeHtml(data.message) + '</span>';
                }
            });
            break;
    }
}
```

注意：`stage_start` 事件中 `data.stage` 值为 `context`/`joint_decision`/`execution`。`joint_decision` stage 对应前端 `stage-task-body` 和 `stage-decision-body` 两个 panel。`decision` SSE 事件携带 `should_remind` + `task_type`。`done` 事件携带 `result`（`MultiFormatContent`）和 `event_id`。

- [ ] **步骤 3：更新 stage panel 映射**

`stage_start` 事件中 `joint_decision` 阶段开始时，同时更新 task 和 decision 两个 panel：

```javascript
case 'stage_start': {
    const stage = data.stage;
    if (stage === 'joint_decision') {
        document.getElementById('stage-task-body').innerHTML =
            '<span class="empty-hint">处理中...</span>';
        document.getElementById('stage-decision-body').innerHTML =
            '<span class="empty-hint">处理中...</span>';
    } else {
        document.getElementById(`stage-${stage}-body`).innerHTML =
            '<span class="empty-hint">处理中...</span>';
    }
    break;
}
```

- [ ] **步骤 4：运行 lint**

```bash
# JS 无 lint 工具，手动检查语法
```

- [ ] **步骤 5：Commit**

```bash
git add webui/app.js
git commit -m "feat: webui uses SSE stream for progressive stage rendering"
```

---

### 任务 6：反馈改 append-only JSONL

**文件：**
- 创建：`app/storage/feedback_log.py`
- 修改：`app/api/routes/feedback.py`
- 修改：`tests/api/test_rest.py`
- 修改：`tests/storage/test_storage.py`

- [ ] **步骤 1：编写 `feedback_log.py`**

```python
"""Append-only 反馈日志，聚合权重计算."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.storage.jsonl_store import JSONLinesStore

if TYPE_CHECKING:
    from pathlib import Path


def feedback_log_store(user_dir: Path) -> JSONLinesStore:
    """获取反馈日志存储实例."""
    return JSONLinesStore(user_dir=user_dir, filename="feedback_log.jsonl")


async def append_feedback(
    user_dir: Path,
    event_id: str,
    action: str,
    feedback_type: str,
) -> None:
    """追加一条反馈记录."""
    store = feedback_log_store(user_dir)
    await store.append({
        "event_id": event_id,
        "action": action,
        "type": feedback_type,
        "timestamp": datetime.now(UTC).isoformat(),
    })


async def aggregate_weights(user_dir: Path) -> dict[str, float]:
    """从反馈日志聚合各类型权重。

    基础权重 0.5，每条 accept +0.1，每条 ignore -0.1。
    结果 clamp 到 [0.1, 1.0]。
    """
    store = feedback_log_store(user_dir)
    records = await store.read_all()
    counts: dict[str, float] = {}
    for rec in records:
        t = rec.get("type", "")
        if not t:
            continue
        delta = 0.1 if rec.get("action") == "accept" else -0.1
        counts[t] = counts.get(t, 0.0) + delta
    return {t: max(0.1, min(1.0, 0.5 + delta)) for t, delta in counts.items()}
```

- [ ] **步骤 2：编写失败测试**

在 `tests/storage/test_storage.py` 追加（不加 `pytest.mark.embedding`，纯存储操作）：

```python
async def test_feedback_log_append_and_aggregate(tmp_path: Path, monkeypatch) -> None:
    """验证反馈日志追加写和权重聚合."""
    from app.storage.feedback_log import append_feedback, aggregate_weights

    monkeypatch.setattr("app.config.DATA_DIR", tmp_path)
    u_dir = tmp_path / "users" / "default"
    u_dir.mkdir(parents=True, exist_ok=True)

    await append_feedback(u_dir, "e1", "accept", "meeting")
    await append_feedback(u_dir, "e2", "accept", "meeting")
    await append_feedback(u_dir, "e3", "ignore", "meeting")

    weights = await aggregate_weights(u_dir)
    assert "meeting" in weights
    # 0.5 + 0.1 + 0.1 - 0.1 = 0.6
    assert weights["meeting"] == pytest.approx(0.6)


async def test_feedback_log_clamp(tmp_path: Path, monkeypatch) -> None:
    """验证权重 clamp 到 [0.1, 1.0]."""
    from app.storage.feedback_log import append_feedback, aggregate_weights

    monkeypatch.setattr("app.config.DATA_DIR", tmp_path)
    u_dir = tmp_path / "users" / "default"
    u_dir.mkdir(parents=True, exist_ok=True)

    for i in range(10):
        await append_feedback(u_dir, f"e{i}", "ignore", "weather")

    weights = await aggregate_weights(u_dir)
    assert weights["weather"] == pytest.approx(0.1)
```

- [ ] **步骤 3：运行测试验证失败**

```bash
uv run pytest tests/storage/test_storage.py::test_feedback_log_append_and_aggregate tests/storage/test_storage.py::test_feedback_log_clamp -v
```

预期：FAIL（`ModuleNotFoundError: No module named 'app.storage.feedback_log'`）

- [ ] **步骤 4：创建 `app/storage/feedback_log.py`**

已在上文步骤 1 中提供代码。写入文件。

- [ ] **步骤 5：运行测试验证通过**

```bash
uv run pytest tests/storage/test_storage.py::test_feedback_log_append_and_aggregate tests/storage/test_storage.py::test_feedback_log_clamp -v
```

预期：PASS

- [ ] **步骤 6：更新 `app/api/routes/feedback.py`**

替换权重更新逻辑。删 `TOMLStore` import，加 `feedback_log` import。

新路由逻辑：

```python
"""反馈路由."""

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException

from app.api.errors import safe_memory_call
from app.api.schemas import FeedbackRequest, FeedbackResponse
from app.config import user_data_dir
from app.memory.schemas import FeedbackData
from app.memory.singleton import get_memory_module
from app.memory.types import MemoryMode
from app.storage.feedback_log import aggregate_weights, append_feedback
from app.storage.toml_store import TOMLStore

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("", response_model=FeedbackResponse)
async def submit_feedback(req: FeedbackRequest) -> FeedbackResponse:
    """提交用户反馈."""
    try:
        mm = get_memory_module()
    except Exception as e:
        logger.exception("submitFeedback failed (get_memory_module)")
        raise HTTPException(status_code=500, detail="Internal server error") from e

    safe_action: Literal["accept", "ignore"] = req.action
    mode = MemoryMode.MEMORY_BANK

    actual_type = await safe_memory_call(
        mm.get_event_type(req.event_id, mode=mode),
        "submitFeedback(get_event_type)",
    )

    if actual_type is None:
        raise HTTPException(
            status_code=404, detail=f"Event not found: {req.event_id!r}"
        )

    feedback = FeedbackData(
        action=safe_action,
        type=actual_type,
        modified_content=req.modified_content,
    )
    await safe_memory_call(
        mm.update_feedback(
            req.event_id,
            feedback,
            mode=mode,
            user_id=req.current_user,
        ),
        "submitFeedback(update_feedback)",
    )

    # 追加写反馈日志（append-only，无并发冲突）
    user_dir = user_data_dir(req.current_user)
    await append_feedback(user_dir, req.event_id, safe_action, actual_type)

    # 从日志聚合权重 → 写入 strategies.toml
    weights = await aggregate_weights(user_dir)
    strategy_store = TOMLStore(
        user_dir=user_dir,
        filename="strategies.toml",
        default_factory=dict,
    )
    await strategy_store.update("reminder_weights", weights)

    return FeedbackResponse(status="success")
```

- [ ] **步骤 7：更新 `tests/api/test_rest.py` 中 `test_feedback_success_updates_strategy_weight`**

测试逻辑不变（验证 strategies.toml 中权重更新），但需确认 `feedback_log.jsonl` 被正确创建。可在测试末尾追加验证：

```python
from app.storage.feedback_log import feedback_log_store

log = feedback_log_store(user_data_dir("default"))
records = await log.read_all()
assert len(records) == 1
assert records[0]["action"] == "accept"
assert records[0]["type"] == "meeting"
```

- [ ] **步骤 8：运行全量测试**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
uv run pytest tests/ -v -x --timeout=60
```

- [ ] **步骤 9：Commit**

```bash
git add -A
git commit -m "feat: append-only feedback log with weight aggregation"
```

---

## 最终验证

- [ ] **步骤 1：全量 lint + 类型检查 + 测试**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check && uv run pytest tests/ -v --timeout=60
```

预期：449 passed, 23 skipped（与基线一致）。

- [ ] **步骤 2：手动集成测试**

```bash
uv run uvicorn app.api.main:app --port 8000
```

浏览器打开 `http://localhost:8000`，验证：
1. 无 GraphQL 链接
2. 无记忆模式选择
3. 输入查询，观察 SSE 逐阶段渲染
4. 反馈按钮可用
5. 事故信息输入"追尾, 施工"，保存预设，加载预设，回填正确

---

## 未解决问题

| 问题 | 可能处理方式 |
|------|-------------|
| SSE 流式在移动端浏览器兼容性？ | (a) fetch ReadableStream 兼容性良好，暂不处理 (b) 加 EventSource polyfill |
| feedback_log.jsonl 增长无限？ | (a) 当前毕设原型，数据量极低，暂不处理 (b) 定期截断或滚动 |
| CORS `*` 生产部署？ | (a) 毕设不部署，保持 (b) 环境变量配置 |
