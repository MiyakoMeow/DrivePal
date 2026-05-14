# API/WebUI 优化实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** API 层路径版本化 + 用户鉴权 + 错误统一 + WebSocket 实时通道 + 前端声明式重构。

**架构：** 新建 `app/api/v1/` 版本化路由，新增 `middleware.py` 处理 X-User-Id，`ws.py` 取代 SSE 流 + 提醒轮询。前端 app.js 重构为 AppState 类 + 声明式表单 + WS 客户端。

**技术栈：** FastAPI WebSocket, Starlette TestClient, Vanilla JS

**基准测试：** `uv run pytest tests/ -q` — 455 passed, 23 skipped

---

### 任务 1：用户身份中间件 + 统一错误信封

**文件：**
- 创建：`app/api/middleware.py`
- 修改：`app/api/errors.py`
- 测试：`tests/api/test_middleware.py`

- [ ] **步骤 1：创建 conftest.py 中 app_client fixture**

`tests/conftest.py` 添加（需 `from tests.fixtures import reset_all_singletons` 及相关 import）：

```python
_MODULES_WITH_DATA_DIR = ["app.config", "app.api.main", "app.memory.singleton"]
_MODULES_WITH_DATA_ROOT = ["app.config"]


@pytest.fixture
def app_client(tmp_path: Path) -> Generator[TestClient, None, None]:
    """提供 TestClient 实例，隔离数据目录。"""
    data_dir = tmp_path / "data"
    os.environ["DATA_DIR"] = str(data_dir)
    target = Path(data_dir)
    with ExitStack() as stack:
        for mod in _MODULES_WITH_DATA_DIR:
            stack.enter_context(patch(f"{mod}.DATA_DIR", target))
        for mod in _MODULES_WITH_DATA_ROOT:
            stack.enter_context(patch(f"{mod}.DATA_ROOT", target))
        reset_all_singletons()
        yield TestClient(app)
        reset_all_singletons()
```

此 fixture 供后续所有 v1 测试使用。

- [ ] **步骤 2：创建中间件**

`app/api/middleware.py`：

```python
"""API 中间件：用户身份提取."""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


class UserIdentityMiddleware(BaseHTTPMiddleware):
    """从 X-User-Id header 提取用户 ID，注入 request.state.user_id。"""

    async def dispatch(self, request: Request, call_next):
        user_id = request.headers.get("X-User-Id", "default")
        request.state.user_id = user_id
        return await call_next(request)
```

- [ ] **步骤 3：重构 errors.py**

新增 `AppErrorCode` 枚举 + `AppError` 异常 + 统一处理函数：

```python
"""REST API 错误处理工具."""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from collections.abc import Awaitable

logger = logging.getLogger(__name__)


class AppErrorCode(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    INVALID_INPUT = "INVALID_INPUT"
    STORAGE_ERROR = "STORAGE_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    STREAM_ERROR = "STREAM_ERROR"


class AppError(HTTPException):
    """带错误码的 HTTP 异常，响应体统一为 {"error": {"code": ..., "message": ...}}。"""

    def __init__(self, code: AppErrorCode, message: str, status_code: int = 500) -> None:
        self.code = code
        super().__init__(status_code=status_code, detail={"error": {"code": code, "message": message}})


async def safe_memory_call[T](
    coro: Awaitable[T],
    context_msg: str,
) -> T:
    """执行记忆系统调用，异常统一转为 AppError. OSError → STORAGE_ERROR, ValueError → INVALID_INPUT, 其余 → INTERNAL_ERROR. """
    try:
        return await coro
    except OSError as e:
        logger.exception("%s failed", context_msg)
        raise AppError(AppErrorCode.STORAGE_ERROR, "Internal storage error", 503) from e
    except ValueError as e:
        logger.exception("%s failed", context_msg)
        raise AppError(AppErrorCode.INVALID_INPUT, "Invalid request data", 422) from e
    except Exception as e:
        logger.exception("%s failed", context_msg)
        raise AppError(AppErrorCode.INTERNAL_ERROR, "Internal server error", 500) from e


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    """AppError → JSON 响应。"""
    return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": exc.detail["error"]["message"]}})
```

- [ ] **步骤 4：编写中间件测试**

`tests/api/test_middleware.py`：

```python
"""用户身份中间件测试."""

from fastapi.testclient import TestClient


def test_default_user_id(app_client: TestClient) -> None:
    """无 X-User-Id header 时默认 'default'。"""
    resp = app_client.get("/api/v1/presets")
    assert resp.status_code == 200


def test_custom_user_id(app_client: TestClient) -> None:
    """X-User-Id header 传入自定义用户。"""
    resp = app_client.get("/api/v1/presets", headers={"X-User-Id": "alice"})
    assert resp.status_code == 200


def test_empty_user_id(app_client: TestClient) -> None:
    """X-User-Id 为空时兜底 default。"""
    resp = app_client.get("/api/v1/presets", headers={"X-User-Id": ""})
    assert resp.status_code == 200
```

- [ ] **步骤 5：运行测试验证失败**

运行：`uv run pytest tests/api/test_middleware.py -v`
预期：FAIL（路由未实现）

- [ ] **步骤 6：实现路由脚手架 + 挂载中间件**

（见任务 2）

- [ ] **步骤 7：运行测试验证通过**

运行：`uv run pytest tests/api/test_middleware.py -v`
预期：PASS

- [ ] **步骤 8：Commit**

```bash
git add -A && git commit -m "feat: add user identity middleware and unified error envelope"
```

---

### 任务 2：v1 路由脚手架 + main.py 改造

**文件：**
- 创建：`app/api/v1/__init__.py`
- 创建：`app/api/v1/query.py`（骨架）
- 创建：`app/api/v1/feedback.py`（骨架）
- 创建：`app/api/v1/presets.py`（骨架）
- 创建：`app/api/v1/data.py`（骨架）
- 创建：`app/api/v1/sessions.py`（骨架）
- 创建：`app/api/v1/reminders.py`（骨架）
- 创建：`app/api/v1/ws.py`（骨架）
- 创建：`app/api/v1/ws_manager.py`（骨架）
- 修改：`app/api/main.py`

- [ ] **步骤 1：创建 `app/api/v1/__init__.py`**

```python
"""API v1 路由包."""
```

- [ ] **步骤 2：创建各路由骨架文件**

每个路由文件导出一个 `router = APIRouter()`，含一个占位健康检查端点。

`app/api/v1/query.py`：

```python
"""v1 查询路由."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok"}
```

其他 5 个文件同模式（仅改模块名）。

`app/api/v1/ws.py`：

```python
"""v1 WebSocket 端点."""

from fastapi import APIRouter

router = APIRouter()
```

`app/api/v1/ws_manager.py`：

```python
"""WebSocket 连接管理器."""

from fastapi import WebSocket


class WSManager:
    def __init__(self) -> None:
        self._conns: dict[str, list[WebSocket]] = {}

    async def connect(self, ws: WebSocket, user_id: str) -> None:
        await ws.accept()
        self._conns.setdefault(user_id, []).append(ws)

    def disconnect(self, ws: WebSocket, user_id: str) -> None:
        conns = self._conns.get(user_id, [])
        self._conns[user_id] = [c for c in conns if c is not ws]

    async def broadcast(self, user_id: str, message: dict) -> None:
        for ws in self._conns.get(user_id, []):
            try:
                await ws.send_json(message)
            except Exception:
                pass

    async def send_to(self, ws: WebSocket, message: dict) -> None:
        await ws.send_json(message)


ws_manager = WSManager()
```

- [ ] **步骤 3：改造 `app/api/main.py`**

```python
"""FastAPI 应用主入口."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.agents.conversation import _conversation_manager
from app.api.middleware import UserIdentityMiddleware
from app.api.errors import AppError, app_error_handler
from app.api.v1.query import router as query_router
from app.api.v1.feedback import router as feedback_router
from app.api.v1.presets import router as presets_router
from app.api.v1.data import router as data_router
from app.api.v1.sessions import router as sessions_router
from app.api.v1.reminders import router as reminders_router
from app.api.v1.ws import router as ws_router
from app.config import DATA_DIR
from app.memory.singleton import _memory_module_state
from app.models.chat import close_client_cache
from app.storage.init_data import init_storage

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

_default_webui = Path(__file__).parent.parent.parent / "webui"
WEBUI_DIR = Path(os.getenv("WEBUI_DIR", _default_webui)).resolve()
if not WEBUI_DIR.exists():
    WEBUI_DIR = _default_webui.resolve()


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_storage()
    logger.info("Data directory initialized: %s", DATA_DIR)
    if not Path.exists(WEBUI_DIR):
        logger.warning("WebUI directory not found: %s", WEBUI_DIR)

    async def _periodic_cleanup() -> None:
        while True:
            await asyncio.sleep(300)
            try:
                _conversation_manager.cleanup_expired()
            except Exception:
                logger.exception("Periodic conversation cleanup failed")

    cleanup_task = asyncio.create_task(_periodic_cleanup())
    yield
    cleanup_task.cancel()
    with suppress(asyncio.CancelledError):
        await cleanup_task
    mm = _memory_module_state[0]
    if mm is not None:
        await mm.close()
        logger.info("MemoryModule closed")
    await close_client_cache()
    logger.info("Chat client cache closed")


app = FastAPI(title="知行车秘 - 车载AI智能体", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(UserIdentityMiddleware)
app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]

app.mount("/static", StaticFiles(directory=WEBUI_DIR), name="static")

# v1 API 路由
API_V1 = APIRouter(prefix="/api/v1")
API_V1.include_router(query_router, prefix="/query", tags=["query"])
API_V1.include_router(feedback_router, prefix="/feedback", tags=["feedback"])
API_V1.include_router(presets_router, prefix="/presets", tags=["presets"])
API_V1.include_router(data_router, tags=["data"])  # data 路由自带路径
API_V1.include_router(sessions_router, prefix="/sessions", tags=["sessions"])
API_V1.include_router(reminders_router, prefix="/reminders", tags=["reminders"])
API_V1.include_router(ws_router, tags=["ws"])
app.include_router(API_V1)


@app.get("/")
async def root() -> FileResponse:
    """返回前端 WebUI 入口页面."""
    return FileResponse(WEBUI_DIR / "index.html")
```

- [ ] **步骤 4：编写 v1 健康检查测试**

`tests/api/test_v1_health.py`：

```python
"""v1 路由健康检查."""

from fastapi.testclient import TestClient


def test_v1_routers_respond(app_client: TestClient) -> None:
    """所有 v1 子路由健康检查端点可访问。"""
    for prefix in ("/api/v1/query", "/api/v1/feedback", "/api/v1/presets", "/api/v1/sessions", "/api/v1/reminders", "/api/v1/data"):
        resp = app_client.get(f"{prefix}/health")
        assert resp.status_code == 200, f"{prefix}/health failed"
```

- [ ] **步骤 5：运行测试**

运行：`uv run pytest tests/api/test_v1_health.py tests/api/test_middleware.py -v`
预期：PASS

- [ ] **步骤 6：Commit**

```bash
git add -A && git commit -m "feat: scaffold v1 API router with middleware"
```

---

### 任务 3：v1 Query 路由

**文件：**
- 修改：`app/api/v1/query.py`

- [ ] **步骤 1：实现 v1 query 路由**

从 `app/api/routes/query.py` 移植。关键变化：
- 路径 `/api/v1/query`
- user_id 从 `request.state.user_id` 读取
- 使用 `AppError` 替代 `HTTPException`

```python
"""v1 查询路由."""

import logging

from fastapi import APIRouter, Request

from app.agents.workflow import AgentWorkflow, ChatModelUnavailableError
from app.api.errors import AppError, AppErrorCode
from app.api.schemas import ProcessQueryResponse
from app.config import DATA_DIR
from app.memory.singleton import get_memory_module
from app.schemas.query import ProcessQueryRequest

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("", response_model=ProcessQueryResponse)
async def process_query(req: ProcessQueryRequest, request: Request) -> ProcessQueryResponse:
    """处理用户查询并返回工作流结果."""
    try:
        mm = get_memory_module()
        workflow = AgentWorkflow(
            data_dir=DATA_DIR,
            memory_module=mm,
            current_user=request.state.user_id,
        )
        ctx = req.context.model_dump() if req.context else None
        result, event_id, stages = await workflow.run_with_stages(
            req.query, ctx, session_id=req.session_id,
        )
        return ProcessQueryResponse(
            result=result, event_id=event_id,
            stages={
                "context": stages.context,
                "task": stages.task,
                "decision": stages.decision,
                "execution": stages.execution,
            },
        )
    except ChatModelUnavailableError as e:
        raise AppError(AppErrorCode.STORAGE_ERROR, "AI model unavailable", 503) from e
```

注意：`request.state.user_id` 由 `UserIdentityMiddleware` 注入。测试时需在请求头加 `X-User-Id`。

- [ ] **步骤 2：编写测试**

`tests/api/test_v1_query.py`：

```python
"""v1 Query 路由测试."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


def test_query_without_context(app_client: TestClient) -> None:
    """POST /api/v1/query 基础请求。"""
    with patch("app.api.v1.query.AgentWorkflow") as mock_wf:
        mock_instance = mock_wf.return_value
        mock_instance.run_with_stages.return_value = ("处理完成", "evt_001", None)
        resp = app_client.post(
            "/api/v1/query",
            json={"query": "明天开会"},
            headers={"X-User-Id": "alice"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"] == "处理完成"
```

- [ ] **步骤 3：运行测试**

运行：`uv run pytest tests/api/test_v1_query.py -v`
预期：PASS

- [ ] **步骤 4：Commit**

```bash
git add -A && git commit -m "feat: port query route to v1 with X-User-Id"
```

---

### 任务 4：v1 Feedback 路由（扩展）

**文件：**
- 修改：`app/api/v1/feedback.py`
- 修改：`app/api/schemas.py`（扩展 FeedbackRequest）

- [ ] **步骤 1：扩展 FeedbackRequest schema**

`app/api/schemas.py`，`action` 字段扩展：

```python
from typing import Literal

# 替换现有 Literal
action: Literal["accept", "ignore", "snooze", "modify"] = "accept"
```

- [ ] **步骤 2：实现 v1 feedback 路由**

`app/api/v1/feedback.py`——从 `app/api/routes/feedback.py` 移植，关键变化：
- `request.state.user_id` 替代 `req.current_user`
- 新增 `snooze` 动作：创建 5 分钟后 pending reminder
- 新增 `modify` 动作：`modified_content` 非空时视为 modify，权重 +0.05
- 使用 `AppError`

```python
"""v1 反馈路由."""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request

from app.api.errors import AppError, AppErrorCode, safe_memory_call
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
async def submit_feedback(req: FeedbackRequest, request: Request) -> FeedbackResponse:
    """提交用户反馈。支持 accept/ignore/snooze/modify。"""
    user_id = request.state.user_id
    try:
        mm = get_memory_module()
    except Exception as e:
        raise AppError(AppErrorCode.INTERNAL_ERROR, "Internal server error") from e

    mode = MemoryMode.MEMORY_BANK

    if req.action in ("accept", "ignore", "modify"):
        actual_type = await safe_memory_call(
            mm.get_event_type(req.event_id, mode=mode),
            "submitFeedback(get_event_type)",
        )
        if actual_type is None:
            raise AppError(AppErrorCode.NOT_FOUND, f"Event not found: {req.event_id!r}", 404)

        feedback = FeedbackData(
            action=req.action if req.action != "modify" else "accept",
            type=actual_type,
            modified_content=req.modified_content,
        )
        await safe_memory_call(
            mm.update_feedback(req.event_id, feedback, mode=mode, user_id=user_id),
            "submitFeedback(update_feedback)",
        )
        user_dir = user_data_dir(user_id)
        await append_feedback(user_dir, req.event_id, req.action, actual_type)
        aggregated = await aggregate_weights(user_dir)
        strategy_store = TOMLStore(user_dir=user_dir, filename="strategies.toml", default_factory=dict)
        await strategy_store.merge_dict_key("reminder_weights", aggregated)

    elif req.action == "snooze":
        # 延后 5 分钟：创建 pending reminder
        from app.agents.pending import PendingReminderManager
        pm = PendingReminderManager(user_data_dir(user_id))
        target_time = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
        await pm.add(
            content={"text": "延后提醒", "detail": req.modified_content or ""},
            trigger_type="time",
            trigger_target={"time": target_time},
            event_id=req.event_id,
            trigger_text="延后 5 分钟",
        )

    return FeedbackResponse(status="success")
```

修改 `app/storage/feedback_log.py` 的 `aggregate_weights`：在 action 分支中加 `modify` → delta = +0.05：

```python
# aggregate_weights 内部修改
if action == "accept":
    delta = 0.1
elif action == "ignore":
    delta = -0.1
elif action == "modify":
    delta = 0.05
else:
    logger.warning("Unknown action %r, skipping", action)
    continue
```

签名不变（无 `delta` 参数）。feedback 路由中删除 `weight_delta` 变量，直接调用 `aggregate_weights(user_dir)`。

- [ ] **步骤 3：编写测试**

`tests/api/test_v1_feedback.py`：

```python
"""v1 Feedback 路由测试."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


def test_feedback_accept(app_client: TestClient) -> None:
    """POST /api/v1/feedback accept 路径。"""
    with patch("app.api.v1.feedback.get_memory_module") as mock_mm:
        mock_instance = AsyncMock()
        mock_instance.get_event_type.return_value = "meeting"
        mock_instance.update_feedback.return_value = None
        mock_mm.return_value = mock_instance
        resp = app_client.post(
            "/api/v1/feedback",
            json={"event_id": "evt_001", "action": "accept"},
            headers={"X-User-Id": "alice"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"


def test_feedback_snooze(app_client: TestClient) -> None:
    """POST /api/v1/feedback snooze 应创建 pending reminder。"""
    with patch("app.api.v1.feedback.PendingReminderManager") as mock_pm:
        mock_instance = AsyncMock()
        mock_instance.add.return_value = AsyncMock(id="pr_001")
        mock_pm.return_value = mock_instance
        resp = app_client.post(
            "/api/v1/feedback",
            json={"event_id": "evt_001", "action": "snooze"},
            headers={"X-User-Id": "alice"},
        )
        assert resp.status_code == 200
        mock_instance.add.assert_called_once()


def test_feedback_modify(app_client: TestClient) -> None:
    """POST /api/v1/feedback modify 应带 modified_content。"""
    with patch("app.api.v1.feedback.get_memory_module") as mock_mm:
        mock_instance = AsyncMock()
        mock_instance.get_event_type.return_value = "meeting"
        mock_instance.update_feedback.return_value = None
        mock_mm.return_value = mock_instance
        resp = app_client.post(
            "/api/v1/feedback",
            json={"event_id": "evt_001", "action": "modify", "modified_content": "改后内容"},
            headers={"X-User-Id": "alice"},
        )
        assert resp.status_code == 200


def test_feedback_not_found(app_client: TestClient) -> None:
    """POST /api/v1/feedback 事件不存在返 404。"""
    with patch("app.api.v1.feedback.get_memory_module") as mock_mm:
        mock_instance = AsyncMock()
        mock_instance.get_event_type.return_value = None
        mock_mm.return_value = mock_instance
        resp = app_client.post(
            "/api/v1/feedback",
            json={"event_id": "nonexistent", "action": "accept"},
            headers={"X-User-Id": "alice"},
        )
        assert resp.status_code == 404
```

- [ ] **步骤 4：运行测试**

运行：`uv run pytest tests/api/test_v1_feedback.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add -A && git commit -m "feat: port feedback route to v1 with snooze/modify actions"
```

---

### 任务 5：v1 Presets / Data / Sessions / Reminders 路由

**文件：**
- 修改：`app/api/v1/presets.py`
- 修改：`app/api/v1/data.py`
- 修改：`app/api/v1/sessions.py`
- 修改：`app/api/v1/reminders.py`

- [ ] **步骤 1：移植 presets 路由**

`app/api/v1/presets.py`——从 `app/api/routes/presets.py` 搬运，将 `current_user` 参数改为 `request.state.user_id`。出口路径 `/api/v1/presets`。

- [ ] **步骤 2：移植 data 路由（增强 export）**

`app/api/v1/data.py`——从 `app/api/routes/data.py` 搬运 + 修改：
- history / export / delete / experiments 路由
- export 加 `type` 查询参数：`events` / `settings` / `all`
- `current_user` → `request.state.user_id`

- [ ] **步骤 3：移植 sessions 路由**

`app/api/v1/sessions.py`——搬运 + user_id 改法同上。

- [ ] **步骤 4：移植 reminders 路由（移除 poll）**

`app/api/v1/reminders.py`——搬运 + 移除 `poll` 端点。保留 `GET /api/v1/reminders`（列表查询）和 `DELETE /api/v1/reminders/{id}`。

- [ ] **步骤 5：编写路由测试**

`tests/api/test_v1_presets.py`：

```python
"""v1 Presets 路由测试."""

from fastapi.testclient import TestClient


def test_list_presets_empty(app_client: TestClient) -> None:
    """GET /api/v1/presets 空列表。"""
    resp = app_client.get("/api/v1/presets")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_save_and_delete_preset(app_client: TestClient) -> None:
    """POST + DELETE /api/v1/presets 完整流程。"""
    save_resp = app_client.post(
        "/api/v1/presets",
        json={"name": "test-parked", "context": {"scenario": "parked"}},
        headers={"X-User-Id": "alice"},
    )
    assert save_resp.status_code == 200
    preset_id = save_resp.json()["id"]

    del_resp = app_client.delete(f"/api/v1/presets/{preset_id}", headers={"X-User-Id": "alice"})
    assert del_resp.status_code == 200
    assert del_resp.json()["success"] is True
```

`tests/api/test_v1_data.py`：

```python
"""v1 Data 路由测试."""

from fastapi.testclient import TestClient


def test_get_history(app_client: TestClient) -> None:
    """GET /api/v1/history 返回列表。"""
    resp = app_client.get("/api/v1/history", headers={"X-User-Id": "alice"})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_export_all(app_client: TestClient) -> None:
    """GET /api/v1/export?type=all 返回文件字典。"""
    resp = app_client.get("/api/v1/export?type=all", headers={"X-User-Id": "alice"})
    assert resp.status_code == 200
    assert "files" in resp.json()


def test_export_events_only(app_client: TestClient) -> None:
    """GET /api/v1/export?type=events 仅返回 jsonl。"""
    resp = app_client.get("/api/v1/export?type=events", headers={"X-User-Id": "alice"})
    assert resp.status_code == 200
    for key in resp.json()["files"]:
        assert key.endswith(".jsonl")
```

`tests/api/test_v1_sessions.py`：

```python
"""v1 Sessions 路由测试."""

from fastapi.testclient import TestClient


def test_close_session(app_client: TestClient) -> None:
    """POST /api/v1/sessions/{id}/close 正常关闭。"""
    resp = app_client.post(
        "/api/v1/sessions/sess_001/close",
        headers={"X-User-Id": "alice"},
    )
    assert resp.status_code == 200
    assert "success" in resp.json()
```

`tests/api/test_v1_reminders.py`：

```python
"""v1 Reminders 路由测试（无 poll）。"""

from fastapi.testclient import TestClient


def test_list_reminders(app_client: TestClient) -> None:
    """GET /api/v1/reminders 返回列表。"""
    resp = app_client.get("/api/v1/reminders", headers={"X-User-Id": "alice"})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_cancel_reminder(app_client: TestClient) -> None:
    """DELETE /api/v1/reminders/{id} 正常取消。"""
    resp = app_client.delete("/api/v1/reminders/rm_001", headers={"X-User-Id": "alice"})
    assert resp.status_code == 200
    assert resp.json()["success"] is True
```

- [ ] **步骤 6：运行测试**

运行：`uv run pytest tests/api/test_v1_*.py -v`
预期：所有 PASS

- [ ] **步骤 7：Commit**

```bash
git add -A && git commit -m "feat: port presets/data/sessions/reminders to v1"
```

---

### 任务 6：WebSocket 连接管理器测试

**文件：**
- 修改：`app/api/v1/ws_manager.py`（已在任务 2 步骤 2 创建骨架，此处确认最终版）

注意：`ws_manager.py` 已在任务 2 步骤 2 以完整代码创建。此任务仅需编写测试验证其行为。

- [ ] **步骤 1：编写 WSManager**

```python
"""WebSocket 连接管理器."""

from fastapi import WebSocket


class WSManager:
    """管理 WebSocket 连接，支持按用户广播。

    每用户可有多连接（多设备场景）。disconnect 幂等。
    """

    def __init__(self) -> None:
        self._conns: dict[str, list[WebSocket]] = {}

    async def connect(self, ws: WebSocket, user_id: str) -> None:
        await ws.accept()
        self._conns.setdefault(user_id, []).append(ws)

    def disconnect(self, ws: WebSocket, user_id: str) -> None:
        conns = self._conns.get(user_id, [])
        self._conns[user_id] = [c for c in conns if c is not ws]

    async def broadcast(self, user_id: str, message: dict) -> None:
        """向用户所有连接广播消息。静默处理断连。"""
        for ws in self._conns.get(user_id, []):
            try:
                await ws.send_json(message)
            except Exception:
                pass  # 断连由心跳超时清理

    async def send_to(self, ws: WebSocket, message: dict) -> None:
        await ws.send_json(message)


# 全局单例
ws_manager = WSManager()
```

- [ ] **步骤 2：编写测试**

`tests/api/test_ws_manager.py`：

```python
"""WSManager 连接管理测试."""

from unittest.mock import AsyncMock, MagicMock

from app.api.v1.ws_manager import WSManager


async def test_connect_and_disconnect() -> None:
    """connect 后列表含该 ws，disconnect 后不含。"""
    manager = WSManager()
    ws = MagicMock()
    ws.accept = AsyncMock()
    await manager.connect(ws, "alice")
    assert ws in manager._conns["alice"]

    manager.disconnect(ws, "alice")
    assert ws not in manager._conns.get("alice", [])


async def test_broadcast_sends_to_all() -> None:
    """broadcast 向用户所有连接发送消息。"""
    manager = WSManager()
    ws1, ws2 = MagicMock(), MagicMock()
    ws1.accept = AsyncMock()
    ws2.accept = AsyncMock()
    ws1.send_json = AsyncMock()
    ws2.send_json = AsyncMock()

    await manager.connect(ws1, "alice")
    await manager.connect(ws2, "alice")
    await manager.broadcast("alice", {"type": "reminder", "payload": {}})

    ws1.send_json.assert_called_once()
    ws2.send_json.assert_called_once()


async def test_broadcast_silent_on_disconnect() -> None:
    """broadcast 时断连不抛异常，静默跳过。"""
    manager = WSManager()
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock(side_effect=RuntimeError("disconnected"))
    await manager.connect(ws, "alice")

    # 不应抛异常
    await manager.broadcast("alice", {"type": "reminder", "payload": {}})
```

- [ ] **步骤 3：运行测试**

运行：`uv run pytest tests/api/test_ws_manager.py -v`
预期：PASS

- [ ] **步骤 4：Commit**

```bash
git add -A && git commit -m "feat: add WebSocket connection manager"
```

---

### 任务 7：WebSocket 端点（取代 SSE 流式 + 提醒推送）

**文件：**
- 创建：`app/api/v1/ws.py`

- [ ] **步骤 1：实现 WS 端点**

`app/api/v1/ws.py`——接收 WS 连接，处理 query → 流式回推各阶段 + 主动推提醒触发。

`AgentWorkflow.run_stream()` 已存在于 `app/agents/workflow.py:857`，返回 `AsyncGenerator[dict]`，每个 yield 为 `{"event": str, "data": dict}`。WS 端点直接消费此生成器，无需新增方法。

```python
"""WebSocket 实时端点：查询流式 + 提醒推送."""

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.agents.workflow import AgentWorkflow
from app.api.v1.ws_manager import ws_manager
from app.config import DATA_DIR
from app.memory.singleton import get_memory_module

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)
router = APIRouter()

_HEARTBEAT_TIMEOUT = 60.0
_PING_INTERVAL = 30.0


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """WebSocket 端点。

    注意：BaseHTTPMiddleware 不处理 WebSocket 连接，因此不从
    request.state 读 user_id，而是直接从 ws.headers 读取 X-User-Id。

    消息协议 JSON 帧：
    client → server: {"type": "query", "payload": {...}}
                     {"type": "ping"}
    server → client: {"type": "stage_start"|"context_done"|"decision"|"done"|"error"|"reminder"|"pong", "payload": {...}}
    """
    user_id = ws.headers.get("x-user-id", "default")
    await ws_manager.connect(ws, user_id)
    logger.info("WS connected: user=%s", user_id)

    try:
        while True:
            raw = await asyncio.wait_for(ws.receive_text(), timeout=_HEARTBEAT_TIMEOUT)
            msg = json.loads(raw)
            msg_type = msg.get("type")

            if msg_type == "ping":
                await ws_manager.send_to(ws, {"type": "pong", "payload": {}})

            elif msg_type == "query":
                payload = msg.get("payload", {})
                await _handle_query(ws, user_id, payload)

            else:
                await ws_manager.send_to(ws, {
                    "type": "error",
                    "payload": {"code": "INVALID_MESSAGE", "message": f"Unknown type: {msg_type}"},
                })

    except asyncio.TimeoutError:
        logger.info("WS heartbeat timeout: user=%s", user_id)
    except WebSocketDisconnect:
        logger.info("WS disconnected: user=%s", user_id)
    except Exception:
        logger.exception("WS error: user=%s", user_id)
    finally:
        ws_manager.disconnect(ws, user_id)


async def _handle_query(ws: WebSocket, user_id: str, payload: dict) -> None:
    """处理查询消息，流式回推各阶段。"""
    query = payload.get("query", "")
    context_raw = payload.get("context")
    session_id = payload.get("session_id")

    mm = get_memory_module()
    workflow = AgentWorkflow(
        data_dir=DATA_DIR,
        memory_module=mm,
        current_user=user_id,
    )

    try:
        async for event in workflow.run_stream(query, context_raw, session_id=session_id):
            await ws_manager.send_to(ws, {
                "type": event["event"],
                "payload": event["data"],
            })
    except Exception as e:
        logger.exception("WS query failed")
        await ws_manager.send_to(ws, {
            "type": "error",
            "payload": {"code": "QUERY_FAILED", "message": str(e)},
        })
```

- [ ] **步骤 2：编写 WS 端点测试**

`tests/api/test_v1_ws.py`——用 `starlette.testclient.WebSocketTestSession`：

```python
"""WebSocket 端点测试."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


async def _mock_run_stream(*args, **kwargs):
    """Mock run_stream 产出固定事件序列。"""
    yield {"event": "stage_start", "data": {"stage": "context"}}
    yield {"event": "context_done", "data": {"context": {"scenario": "parked"}}}
    yield {"event": "stage_start", "data": {"stage": "joint_decision"}}
    yield {"event": "decision", "data": {"task_type": "general", "should_remind": True}}
    yield {"event": "stage_start", "data": {"stage": "execution"}}
    yield {"event": "done", "data": {"status": "delivered", "event_id": "evt_001", "result": {"text": "提醒已发送"}}}


def test_ws_query_flow(app_client: TestClient) -> None:
    """WS 查询应流式返回各阶段事件。"""
    with patch("app.api.v1.ws.AgentWorkflow") as mock_wf:
        mock_instance = mock_wf.return_value
        mock_instance.run_stream = _mock_run_stream
        with app_client.websocket_connect("/api/v1/ws", headers={"X-User-Id": "test"}) as ws:
            ws.send_json({"type": "query", "payload": {"query": "明天开会"}})
            events = []
            for _ in range(6):
                raw = ws.receive_text()
                msg = json.loads(raw)
                events.append(msg["type"])
            assert "stage_start" in events
            assert "done" in events


def test_ws_ping_pong(app_client: TestClient) -> None:
    """WS ping/pong 应正确响应。"""
    with app_client.websocket_connect("/api/v1/ws", headers={"X-User-Id": "test"}) as ws:
        ws.send_json({"type": "ping"})
        raw = ws.receive_text()
        msg = json.loads(raw)
        assert msg["type"] == "pong"
```

- [ ] **步骤 3：运行测试**

运行：`uv run pytest tests/api/test_v1_ws.py -v`
预期：PASS

- [ ] **步骤 4：Commit**

```bash
git add -A && git commit -m "feat: add WebSocket endpoint replacing SSE streaming"
```

---

### 任务 8：前端重构 — app.js

**文件：**
- 修改：`webui/app.js`
- 修改：`webui/index.html`
- 修改：`webui/styles.css`

- [ ] **步骤 1：AppState 类**

封装所有共享状态：

```js
class AppState {
  #currentEventId = null;
  #experimentChart = null;
  #ws = null;
  #wsReconnectTimer = null;
  reconnectAttempts = 0;  // 非私有，供 connectWS/scheduleReconnect 读写

  getCurrentEventId() { return this.#currentEventId; }
  setCurrentEventId(id) { this.#currentEventId = id; }

  setChart(chart) { this.#experimentChart = chart; }
  getChart() { return this.#experimentChart; }
  destroyChart() { if (this.#experimentChart) { this.#experimentChart.destroy(); this.#experimentChart = null; } }

  setWs(ws) { this.#ws = ws; }
  getWs() { return this.#ws; }

  reset() {
    this.#currentEventId = null;
    this.destroyChart();
    this.reconnectAttempts = 0;
    document.getElementById('feedbackRow').style.display = 'none';
    ['context','task','decision','execution'].forEach(s => {
      document.getElementById(`stage-${s}-body`).innerHTML = '<span class="empty-hint">等待查询...</span>';
    });
  }

  destroy() {
    if (this.#ws) { this.#ws.close(); this.#ws = null; }
    this.destroyChart();
    if (this.#wsReconnectTimer) { clearTimeout(this.#wsReconnectTimer); }
  }
}

const state = new AppState();
```

- [ ] **步骤 2：声明式表单函数**

```js
function buildContext(rootEl) {
  const ctx = {};
  rootEl.querySelectorAll('[data-ctx-path]').forEach(el => {
    const path = el.dataset.ctxPath.split('.');
    let val = el.value;
    if (el.type === 'number' || el.type === 'range') val = parseFloat(val) || 0;
    if (val === '' || val === null || val === undefined) return;
    let cur = ctx;
    for (let i = 0; i < path.length - 1; i++) {
      cur[path[i]] = cur[path[i]] || {};
      cur = cur[path[i]];
    }
    cur[path[path.length - 1]] = val;
  });
  return Object.keys(ctx).length ? ctx : null;
}

function fillContext(rootEl, ctx) {
  rootEl.querySelectorAll('[data-ctx-path]').forEach(el => {
    const path = el.dataset.ctxPath.split('.');
    let val = ctx;
    for (const key of path) {
      if (val == null) break;
      val = val[key];
    }
    if (val != null) el.value = val;
  });
}

function resetContext(rootEl) {
  rootEl.querySelectorAll('[data-ctx-path]').forEach(el => {
    if (el.type === 'range') { el.value = 0; }
    else if (el.type === 'number') { el.value = ''; }
    else { el.value = ''; }
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}
```

- [ ] **步骤 3：HTML data-ctx-path 改造**

`webui/index.html`——给每个上下文 input 加 `data-ctx-path`：

```html
<select id="ctx-emotion" data-ctx-path="driver.emotion">
<input type="number" step="any" id="ctx-lat" data-ctx-path="spatial.current_location.latitude" placeholder="例: 39.9042">
```

全部字段映射：
- `ctx-emotion` → `driver.emotion`
- `ctx-workload` → `driver.workload`
- `ctx-fatigueLevel` → `driver.fatigue_level`
- `ctx-lat` → `spatial.current_location.latitude`
- `ctx-lng` → `spatial.current_location.longitude`
- `ctx-address` → `spatial.current_location.address`
- `ctx-speedKmh` → `spatial.current_location.speed_kmh`
- `ctx-dest-address` → `spatial.destination.address`
- `ctx-etaMinutes` → `spatial.eta_minutes`
- `ctx-congestionLevel` → `traffic.congestion_level`
- `ctx-incidents` → `traffic.incidents`
- `ctx-delayMinutes` → `traffic.estimated_delay_minutes`
- `ctx-scenario` → `scenario`

删除 `getContextInput()`、`fillForm()`、`clearForm()`，替换为通用函数调用。

- [ ] **步骤 4：WebSocket 客户端**

```js
function connectWS() {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${location.host}/api/v1/ws`;
  const ws = new WebSocket(wsUrl);
  ws.onopen = () => { state.setWs(ws); state.reconnectAttempts = 0; };
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    handleWSMessage(msg.type, msg.payload);
  };
  ws.onclose = () => {
    state.setWs(null);
    scheduleReconnect();
  };
  ws.onerror = () => { ws.close(); };
  return ws;
}

function scheduleReconnect() {
  const delay = Math.min(1000 * Math.pow(2, state.reconnectAttempts), 30000);
  state.reconnectAttempts += 1;
  setTimeout(() => connectWS(), delay);
}

function handleWSMessage(type, payload) {
  switch (type) {
    case 'stage_start':
      if (payload.stage === 'joint_decision') {
        document.getElementById('stage-task-body').innerHTML = '<span class="empty-hint">处理中...</span>';
        document.getElementById('stage-decision-body').innerHTML = '<span class="empty-hint">处理中...</span>';
      } else {
        document.getElementById(`stage-${payload.stage}-body`).innerHTML = '<span class="empty-hint">处理中...</span>';
      }
      break;
    case 'context_done':
      document.getElementById('stage-context-body').textContent = formatJson(payload.context);
      break;
    case 'decision':
      document.getElementById('stage-task-body').textContent = formatJson({ task_type: payload.task_type });
      document.getElementById('stage-decision-body').textContent = formatJson(payload);
      break;
    case 'done':
      if (payload.event_id) { state.setCurrentEventId(payload.event_id); document.getElementById('feedbackRow').style.display = 'flex'; }
      handleDone(payload);
      loadHistory();
      break;
    case 'error':
      showToast(payload.message || '未知错误', 'error');
      break;
    case 'reminder':
      showToast('新提醒: ' + (payload.content?.text || ''), 'info');
      break;
  }
}
```

- [ ] **步骤 5：Toast 通知**

```js
function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer') || (() => {
    const c = document.createElement('div');
    c.id = 'toastContainer';
    c.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:9999;display:flex;flex-direction:column;gap:8px;';
    document.body.appendChild(c);
    return c;
  })();
  const el = document.createElement('div');
  el.style.cssText = `padding:10px 16px;border-radius:6px;color:#fff;font-size:13px;max-width:360px;word-wrap:break-word;background:${type === 'error' ? '#dc3545' : type === 'info' ? '#007bff' : '#6c757d'};box-shadow:0 2px 8px rgba(0,0,0,.15);animation:fadeIn .2s;`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity .3s'; setTimeout(() => el.remove(), 300); }, 4000);
}
```

- [ ] **步骤 6：修改 sendQuery 使用 WS**

```js
async function sendQuery() {
  const query = document.getElementById('queryInput').value.trim();
  if (!query) return;

  const context = buildContext(document.querySelector('.panel-left'));
  if (!state.getWs() || state.getWs().readyState !== WebSocket.OPEN) {
    showToast('WebSocket 未连接，正在重连...', 'error');
    connectWS();
    return;
  }

  setLoading(true);
  state.reset();
  document.getElementById('feedbackRow').style.display = 'none';

  const ws = state.getWs();
  ws.send(JSON.stringify({
    type: 'query',
    payload: { query, context, session_id: 'webui-' + Date.now() },
  }));

  setLoading(false);
}
```

- [ ] **步骤 7：初始化自动连接 WS**

```js
// 页面加载
loadPresets();
loadHistory();
loadExperimentData();
connectWS();

// 定期 ping
setInterval(() => {
  const ws = state.getWs();
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }));
}, 30000);
```

移除旧 SSE parser 代码和 `handleSSEEvent`。

- [ ] **步骤 8：更新反馈按钮**

`webui/index.html` 中反馈行扩展为四按钮：

```html
<div class="feedback-row" id="feedbackRow" style="display:none; padding: 0 14px 12px;">
    <button class="btn btn-success btn-sm" onclick="submitFeedback('accept')">接受</button>
    <button class="btn btn-secondary btn-sm" onclick="submitFeedback('ignore')">忽略</button>
    <button class="btn btn-secondary btn-sm" onclick="submitFeedback('snooze')">延后5分钟</button>
    <button class="btn btn-secondary btn-sm" onclick="submitFeedback('modify')">修改</button>
</div>
```

`submitFeedback` 函数中 `modify` 分支弹出 `prompt()` 编辑内容：

```js
async function submitFeedback(action) {
  const eventId = state.getCurrentEventId();
  if (!eventId) return;
  const body = { event_id: eventId, action };
  if (action === 'modify') {
    const content = prompt('请输入修改后的内容:');
    if (!content) return;
    body.modified_content = content;
  }
  try {
    await api('POST', '/api/v1/feedback', body);
    document.getElementById('feedbackRow').style.display = 'none';
  } catch (e) {
    showToast('反馈提交失败: ' + e.message, 'error');
  }
}
```

注意：`api()` 函数需更新——加 `X-User-Id` header：

```js
async function api(method, path, body) {
    const opts = {
        method,
        headers: {
            'Content-Type': 'application/json',
            'X-User-Id': 'default',  // 毕设固定 default
        },
    };
    if (body) opts.body = JSON.stringify(body);
    const resp = await fetch(path, opts);
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.error?.message || err.detail || `HTTP ${resp.status}`);
    }
    return resp.json();
}
```

- [ ] **步骤 9：手工验证**

启动：`uv run uvicorn app.api.main:app`
打开浏览器访问 `http://127.0.0.1:34567`，确认：
- 页面加载无误
- 表单字段可用
- 发送查询后各阶段正常显示
- 反馈按钮可用
- 历史记录正常加载
- 实验图表可加载

- [ ] **步骤 10：Commit**

```bash
git add -A && git commit -m "refactor: rewrite webui with AppState, declarative form, WebSocket"
```

---

### 任务 9：清理旧代码

**文件：**
- 删除：`app/api/stream.py`
- 删除：`app/api/routes/`（整个目录）
- 删除：`app/api/v1/` 中各路由的 `health` 占位端点

- [ ] **步骤 1：删除旧路由代码**

```bash
git rm -r app/api/routes/
git rm app/api/stream.py
```

- [ ] **步骤 2：移除 v1 路由中的 health 占位**

各 v1 路由文件的 `@router.get("/health")` 端点删除。

- [ ] **步骤 3：更新 main.py 导入**

移除对 `app.api.stream` 的引用。更新 `app/api/main.py`：删除 `from app.api.stream import router as stream_router`。

- [ ] **步骤 4：运行测试**

运行：`uv run pytest tests/ -q`
预期：PASS（现有测试可能因路径变更而跳过，新增的 v1 测试应全部 PASS）

- [ ] **步骤 5：Commit**

```bash
git add -A && git commit -m "refactor: remove deprecated routes/ and stream.py"
```

---

### 任务 10：更新旧测试 + 全量验证

**文件：**
- 修改：`tests/api/test_rest.py`（适配新路径 + X-User-Id header）
- 修改：`tests/agents/test_sse_stream.py`（标记跳过或删除）
- 修改：`tests/conftest.py`（添加 app_client fixture）

- [ ] **步骤 1：清理 conftest.py**

`tests/conftest.py` 中的 `app_client` fixture 已在任务 1 步骤 1 添加。此处删除旧的 `isolated_app` fixture（来自原 `test_rest.py`），避免重复定义。若 `test_rest.py` 中有局部 fixture 定义也一并移除。

- [ ] **步骤 2：更新 test_rest.py**

`tests/api/test_rest.py`——改用 `app_client` fixture，路径前缀 `/api/v1/`，加 `X-User-Id` header。删除已迁移的测试用例避免重复。

- [ ] **步骤 3：调整 test_sse_stream.py**

添加 `pytest.mark.skip("SSE replaced by WebSocket")` 或删除文件。

- [ ] **步骤 4：全量运行测试**

运行：`uv run pytest tests/ -q --timeout=30`
预期：与基准一致或更优（455+ passed, 23 skipped）

- [ ] **步骤 5：运行 lint + 类型检查**

```bash
uv run ruff check --fix
uv run ruff format
uv run ty check
```

预期：全部通过

- [ ] **步骤 6：Commit**

```bash
git add -A && git commit -m "test: update tests for v1 API and WebSocket"
```

---

### 任务 11：PendingReminder WS 回调 + AGENTS.md 更新

**文件：**
- 修改：`app/agents/pending.py`（添加 WS 回调）
- 修改：`app/api/AGENTS.md`（更新文档）

- [ ] **步骤 1：PendingReminder 添加触发通知**

`app/agents/pending.py` 的 `poll()` 方法中，触发提醒后通过 `ws_manager` 广播给对应用户：

```python
# pending.py 顶部新增导入
from app.api.v1.ws_manager import ws_manager

# poll() 方法中，触发后加广播
async def poll(self, driving_context: dict) -> list[dict]:
    ...
    triggered = [...]
    for r in triggered:
        await ws_manager.broadcast(
            self._user_id,  # 需在 __init__ 中记录
            {"type": "reminder", "payload": r},
        )
    return triggered
```

注意：`PendingReminderManager.__init__` 需新增 `user_id` 参数（从 `user_data_dir` 推断或显式传入）。

- [ ] **步骤 2：编写测试**

`tests/agents/test_pending.py` 补充：验证 `poll()` 触发后 `ws_manager.broadcast` 被调用。

- [ ] **步骤 3：运行测试**

运行：`uv run pytest tests/agents/test_pending.py -v`
预期：PASS

- [ ] **步骤 4：更新 `app/api/AGENTS.md`**

重写端点表和架构说明，反映 v1 路由 + WebSocket + X-User-Id：

```markdown
# API 层

`app/api/` — FastAPI REST + WebSocket。

## 版本

所有端点 `/api/v1/` 前缀。

## 鉴权

`X-User-Id` header → `request.state.user_id`。缺失默认 `"default"`。

## 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/api/v1/query` | 处理查询，返完整工作流结果 |
| WS   | `/api/v1/ws` | WebSocket 实时通道（查询流式+提醒推送） |
| POST | `/api/v1/feedback` | 提交反馈(accept/ignore/snooze/modify) |
| GET  | `/api/v1/history` | 查询历史记忆事件 |
| GET  | `/api/v1/export` | 导出当前用户全量文本数据(?type=events|settings|all) |
| DELETE | `/api/v1/data` | 删除当前用户全量数据 |
| GET  | `/api/v1/experiments` | 查询实验结果对比 |
| GET/POST/DELETE | `/api/v1/presets` | 场景预设 CRUD |
| GET/DELETE | `/api/v1/reminders` | 提醒列表/取消 |
| POST | `/api/v1/sessions/{id}/close` | 关闭会话 |

## WebSocket 协议

JSON 帧。客户端发送 query/ping，服务端返回 stage_start/context_done/decision/done/error/reminder/pong。

## 错误处理

统一信封：`{"error": {"code": "...", "message": "..."}}`。
```

- [ ] **步骤 5：Commit**

```bash
git add -A && git commit -m "feat: add WS callback to PendingReminder + update AGENTS.md"
```

---

### 未解决问题

1. WebSocket 鉴权——当前 upgrade 时未校验 X-User-Id（WS 握手时 header 可用），但毕设范围不要求。
2. WS 长连接下的 session 管理——当前每次 query 自带 `session_id`，无显式握手。简单场景够用。
