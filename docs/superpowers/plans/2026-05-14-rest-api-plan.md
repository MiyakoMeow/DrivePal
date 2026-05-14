# REST API 替换实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将 Strawberry GraphQL API 层替换为 FastAPI 原生 REST 路由，消除类型重复和转换层。

**架构：** 删除 graphql_schema.py / converters.py / errors.py / resolvers/。新建 `app/api/routes/` 目录按资源分文件注册 REST 路由，新建 `app/api/schemas.py` 定义 REST 专用 request/response Pydantic 模型。Pydantic 模型直接作 FastAPI schema，零转换。

**技术栈：** FastAPI + Pydantic（已有依赖）。删除 strawberry-graphql。

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `app/api/schemas.py` | REST request/response Pydantic 模型（新建） |
| `app/api/routes/__init__.py` | 汇总注册所有子路由（新建） |
| `app/api/routes/query.py` | `POST /api/query`（新建） |
| `app/api/routes/feedback.py` | `POST /api/feedback`（新建） |
| `app/api/routes/presets.py` | `GET/POST/DELETE /api/presets`（新建） |
| `app/api/routes/data.py` | `GET /api/history`、`GET /api/export`、`DELETE /api/data`、`GET /api/experiments`（新建） |
| `app/api/routes/reminders.py` | `GET/POST/DELETE /api/reminders`（新建） |
| `app/api/routes/sessions.py` | `POST /api/sessions/{session_id}/close`（新建） |
| `app/api/main.py` | 删 GraphQL mount，改注册 REST 路由（修改） |
| `app/api/stream.py` | 不动 |
| `app/schemas/context.py` | 不动 |
| `app/schemas/query.py` | 不动 |
| `webui/app.js` | GraphQL fetch → REST fetch（修改） |
| `pyproject.toml` | 删 strawberry-graphql 依赖（修改） |
| `tests/api/test_graphql.py` | 重写为 `tests/api/test_rest.py`（重命名+重写） |

---

### 任务 1：创建 REST request/response schemas

**文件：**
- 创建：`app/api/schemas.py`
- 测试：无独立测试（由路由测试间接覆盖）

- [ ] **步骤 1：编写 `app/api/schemas.py`**

此文件定义所有 REST 端点专用的 Pydantic request/response 模型。

```python
"""REST API request/response schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.schemas.context import DrivingContext


# --- Query ---

class ProcessQueryResponse(BaseModel):
    """POST /api/query 响应."""

    result: str
    event_id: str | None = None
    stages: dict | None = None  # {context, task, decision, execution}


# --- Feedback ---

class FeedbackRequest(BaseModel):
    """POST /api/feedback 请求."""

    event_id: str
    action: Literal["accept", "ignore"]
    memory_mode: str = "memory_bank"
    modified_content: str | None = None
    current_user: str = "default"


class FeedbackResponse(BaseModel):
    """POST /api/feedback 响应."""

    status: str


# --- Presets ---

class SavePresetRequest(BaseModel):
    """POST /api/presets 请求."""

    name: str
    context: DrivingContext
    current_user: str = "default"


class ScenarioPresetResponse(BaseModel):
    """GET /api/presets 响应项."""

    id: str
    name: str
    context: DrivingContext
    created_at: str


# --- History ---

class MemoryEventResponse(BaseModel):
    """GET /api/history 响应项."""

    id: str
    content: str
    type: str
    description: str
    created_at: str


# --- Export ---

class ExportDataResponse(BaseModel):
    """GET /api/export 响应."""

    files: dict[str, str]


# --- Experiments ---

class ExperimentResultResponse(BaseModel):
    """单策略实验结果."""

    strategy: str
    exact_match: float
    field_f1: float
    value_f1: float


class ExperimentResultsResponse(BaseModel):
    """GET /api/experiments 响应."""

    strategies: list[ExperimentResultResponse]


# --- Reminders ---

class PollRemindersRequest(BaseModel):
    """POST /api/reminders/poll 请求."""

    current_user: str = "default"
    context: DrivingContext | None = None


class TriggeredReminderResponse(BaseModel):
    """已触发提醒."""

    id: str
    event_id: str
    content: dict
    triggered_at: str


class PollRemindersResponse(BaseModel):
    """POST /api/reminders/poll 响应."""

    triggered: list[TriggeredReminderResponse]


class PendingReminderResponse(BaseModel):
    """GET /api/reminders 响应项."""

    id: str
    event_id: str
    trigger_type: str
    trigger_text: str
    status: str
    created_at: str
```

- [ ] **步骤 2：运行 lint/type 检查**

```bash
uv run ruff check --fix app/api/schemas.py && uv run ruff format app/api/schemas.py && uv run ty check app/api/schemas.py
```

预期：全部通过。

- [ ] **步骤 3：Commit**

```bash
git add app/api/schemas.py
git commit -m "feat(api): add REST request/response schemas"
```

---

### 任务 2：创建 data 路由（history、export、delete、experiments）

**文件：**
- 创建：`app/api/routes/data.py`
- 参考实现：`app/api/resolvers/query.py`（history、experimentResults）+ `app/api/resolvers/mutation.py`（exportData、deleteAllData）

- [ ] **步骤 1：编写 `app/api/routes/data.py`**

从 query.py 和 mutation.py 提取对应 resolver 逻辑，改为 FastAPI 路由函数。

```python
"""数据查询与管理路由（history、export、delete、experiments）."""

import logging
import shutil

from fastapi import APIRouter, HTTPException

from app.api.schemas import (
    ExperimentResultResponse,
    ExperimentResultsResponse,
    ExportDataResponse,
    MemoryEventResponse,
)
from app.config import user_data_dir
from app.memory.singleton import get_memory_module
from app.memory.types import MemoryMode
from app.storage.experiment_store import read_benchmark

logger = logging.getLogger(__name__)
router = APIRouter()


def _safe_float(metrics: dict, key: str) -> float:
    """安全获取 metric 值."""
    try:
        return float(metrics.get(key, 0.0))
    except ValueError, TypeError:
        return 0.0


@router.get("/history", response_model=list[MemoryEventResponse])
async def get_history(
    limit: int = 10,
    memory_mode: str = "memory_bank",
    current_user: str = "default",
) -> list[MemoryEventResponse]:
    """查询历史记忆事件."""
    mm = get_memory_module()
    mode = MemoryMode(memory_mode)
    events = await mm.get_history(limit=limit, mode=mode, user_id=current_user)
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


@router.get("/export", response_model=ExportDataResponse)
async def export_data(current_user: str = "default") -> ExportDataResponse:
    """导出当前用户全量文本数据."""
    u_dir = user_data_dir(current_user)
    files: dict[str, str] = {}
    if not u_dir.exists():
        return ExportDataResponse(files=files)

    allowed_suffixes = (".jsonl", ".toml", ".json")
    for fpath in u_dir.rglob("*"):
        if "memorybank" in fpath.parts or fpath.suffix not in allowed_suffixes:
            continue
        if fpath.is_file():
            try:
                content = fpath.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            rel = str(fpath.relative_to(u_dir))
            files[rel] = content
    return ExportDataResponse(files=files)


@router.delete("/data")
async def delete_all_data(current_user: str = "default") -> dict[str, bool]:
    """删除当前用户全量数据."""
    u_dir = user_data_dir(current_user)
    if not u_dir.exists():
        return {"success": False}
    try:
        shutil.rmtree(u_dir)
    except OSError as e:
        logger.warning("Failed to delete user data: %s", e)
        return {"success": False}
    return {"success": True}


@router.get("/experiments", response_model=ExperimentResultsResponse)
async def get_experiment_results() -> ExperimentResultsResponse:
    """查询五策略实验结果对比."""
    try:
        data = read_benchmark()
    except (OSError, ValueError) as e:
        logger.warning("Failed to read experiment benchmark: %s", e)
        data = {}
    strategies = []
    for name, metrics in data.get("strategies", {}).items():
        try:
            strategies.append(
                ExperimentResultResponse(
                    strategy=name,
                    exact_match=_safe_float(metrics, "exact_match"),
                    field_f1=_safe_float(metrics, "field_f1"),
                    value_f1=_safe_float(metrics, "value_f1"),
                )
            )
        except (ValueError, TypeError) as e:
            logger.warning("Skipping invalid strategy %s: %s", name, e)
    return ExperimentResultsResponse(strategies=strategies)
```

- [ ] **步骤 2：lint/type 检查**

```bash
uv run ruff check --fix app/api/routes/data.py && uv run ruff format app/api/routes/data.py && uv run ty check app/api/routes/data.py
```

- [ ] **步骤 3：Commit**

```bash
git add app/api/routes/data.py
git commit -m "feat(api): add data routes (history, export, delete, experiments)"
```

---

### 任务 3：创建 presets 路由

**文件：**
- 创建：`app/api/routes/presets.py`
- 参考实现：`app/api/resolvers/converters.py`（preset_store、to_gql_preset 的 TOML None 还原逻辑）+ `app/api/resolvers/mutation.py`（saveScenarioPreset、deleteScenarioPreset）+ `app/api/resolvers/query.py`（scenarioPresets）

- [ ] **步骤 1：编写 `app/api/routes/presets.py`**

关键点：`to_gql_preset` 中的 TOML None 还原逻辑（空字符串→None）需内联保留。

```python
"""场景预设路由."""

from fastapi import APIRouter

from app.api.schemas import SavePresetRequest, ScenarioPresetResponse
from app.config import user_data_dir
from app.schemas.context import DrivingContext, ScenarioPreset
from app.storage.toml_store import TOMLStore

router = APIRouter()


def _preset_store(current_user: str = "default") -> TOMLStore:
    """获取场景预设存储实例."""
    return TOMLStore(
        user_dir=user_data_dir(current_user),
        filename="scenario_presets.toml",
        default_factory=list,
    )


def _restore_toml_nones(ctx_raw: dict) -> dict:
    """TOML 不支持 None，_clean_for_toml 将 None 序列化为空字符串，此处还原."""
    safe = {k: v for k, v in ctx_raw.items() if k in DrivingContext.model_fields}
    sp = safe.get("spatial", {})
    if isinstance(sp, dict):
        for key in ("destination", "eta_minutes", "heading"):
            if sp.get(key) == "":
                sp[key] = None
    return safe


def _dict_to_preset_response(p: dict) -> ScenarioPresetResponse:
    """存储 dict → ScenarioPresetResponse."""
    ctx_raw = p.get("context", {})
    safe = _restore_toml_nones(ctx_raw)
    ctx = DrivingContext.model_validate(safe)
    return ScenarioPresetResponse(
        id=p.get("id", ""),
        name=p.get("name", ""),
        context=ctx,
        created_at=p.get("created_at", ""),
    )


@router.get("", response_model=list[ScenarioPresetResponse])
async def list_presets(
    current_user: str = "default",
) -> list[ScenarioPresetResponse]:
    """查询所有场景预设."""
    store = _preset_store(current_user)
    presets = await store.read()
    return [_dict_to_preset_response(p) for p in presets]


@router.post("", response_model=ScenarioPresetResponse)
async def save_preset(req: SavePresetRequest) -> ScenarioPresetResponse:
    """保存场景预设."""
    store = _preset_store(req.current_user)
    preset = ScenarioPreset(name=req.name, context=req.context)
    await store.append(preset.model_dump())
    return _dict_to_preset_response(preset.model_dump())


@router.delete("/{preset_id}")
async def delete_preset(
    preset_id: str,
    current_user: str = "default",
) -> dict[str, bool]:
    """删除场景预设."""
    store = _preset_store(current_user)
    presets = await store.read()
    new_presets = [p for p in presets if p.get("id") != preset_id]
    if len(new_presets) == len(presets):
        return {"success": False}
    await store.write(new_presets)
    return {"success": True}
```

- [ ] **步骤 2：lint/type 检查**

```bash
uv run ruff check --fix app/api/routes/presets.py && uv run ruff format app/api/routes/presets.py && uv run ty check app/api/routes/presets.py
```

- [ ] **步骤 3：Commit**

```bash
git add app/api/routes/presets.py
git commit -m "feat(api): add presets routes (list, save, delete)"
```

---

### 任务 4：创建 query 路由

**文件：**
- 创建：`app/api/routes/query.py`
- 参考实现：`app/api/resolvers/mutation.py` process_query 方法

- [ ] **步骤 1：编写 `app/api/routes/query.py`**

```python
"""查询处理路由."""

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException

from app.agents.workflow import AgentWorkflow, ChatModelUnavailableError
from app.api.schemas import ProcessQueryResponse
from app.config import DATA_DIR
from app.memory.singleton import get_memory_module
from app.memory.types import MemoryMode
from app.schemas.query import ProcessQueryRequest

if TYPE_CHECKING:
    from collections.abc import Awaitable

logger = logging.getLogger(__name__)
router = APIRouter()


async def _safe_memory_call[T](
    coro: "Awaitable[T]",
    context_msg: str,
) -> T:
    """执行记忆系统调用，异常统一转为 HTTPException."""
    try:
        return await coro
    except OSError as e:
        logger.exception("%s failed", context_msg)
        raise HTTPException(status_code=500, detail="Internal storage error") from e
    except RuntimeError as e:
        logger.exception("%s failed", context_msg)
        raise HTTPException(status_code=500, detail="Internal runtime error") from e
    except ValueError as e:
        logger.exception("%s failed", context_msg)
        raise HTTPException(status_code=422, detail=f"Invalid data in {context_msg}") from e
    except Exception as e:
        logger.exception("%s failed", context_msg)
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.post("/query", response_model=ProcessQueryResponse)
async def process_query(req: ProcessQueryRequest) -> ProcessQueryResponse:
    """处理用户查询并返回工作流结果."""
    try:
        mm = get_memory_module()
        workflow = AgentWorkflow(
            data_dir=DATA_DIR,
            memory_mode=MemoryMode(req.memory_mode),
            memory_module=mm,
            current_user=req.current_user,
        )

        result, event_id, stages = await workflow.run_with_stages(
            req.query,
            req.context,
            session_id=req.session_id,
        )
        return ProcessQueryResponse(
            result=result,
            event_id=event_id,
            stages={
                "context": stages.context,
                "task": stages.task,
                "decision": stages.decision,
                "execution": stages.execution,
            },
        )
    except ChatModelUnavailableError as e:
        raise HTTPException(
            status_code=503,
            detail="AI 模型未就绪",
        ) from e
    except Exception as e:
        logger.exception("processQuery failed")
        raise HTTPException(status_code=500, detail="Internal server error") from e
```

- [ ] **步骤 2：lint/type 检查**

```bash
uv run ruff check --fix app/api/routes/query.py && uv run ruff format app/api/routes/query.py && uv run ty check app/api/routes/query.py
```

- [ ] **步骤 3：Commit**

```bash
git add app/api/routes/query.py
git commit -m "feat(api): add query route (POST /api/query)"
```

---

### 任务 5：创建 feedback 路由

**文件：**
- 创建：`app/api/routes/feedback.py`
- 参考实现：`app/api/resolvers/mutation.py` submit_feedback 方法

- [ ] **步骤 1：编写 `app/api/routes/feedback.py`**

```python
"""反馈路由."""

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException

from app.api.routes.query import _safe_memory_call
from app.api.schemas import FeedbackRequest, FeedbackResponse
from app.config import user_data_dir
from app.memory.schemas import FeedbackData
from app.memory.singleton import get_memory_module
from app.memory.types import MemoryMode
from app.storage.toml_store import TOMLStore

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(req: FeedbackRequest) -> FeedbackResponse:
    """提交用户反馈."""
    try:
        mm = get_memory_module()
    except Exception as e:
        logger.exception("submitFeedback failed (get_memory_module)")
        raise HTTPException(status_code=500, detail="Internal server error") from e

    safe_action: Literal["accept", "ignore"] = req.action
    mode = MemoryMode(req.memory_mode)

    actual_type = await _safe_memory_call(
        mm.get_event_type(req.event_id, mode=mode),
        "submitFeedback(get_event_type)",
    )

    if actual_type is None:
        raise HTTPException(status_code=404, detail=f"Event not found: {req.event_id!r}")

    feedback = FeedbackData(
        action=safe_action,
        type=actual_type,
        modified_content=req.modified_content,
    )
    await _safe_memory_call(
        mm.update_feedback(
            req.event_id,
            feedback,
            mode=mode,
            user_id=req.current_user,
        ),
        "submitFeedback(update_feedback)",
    )

    # 权重更新：读→改→写 strategies.toml
    user_dir = user_data_dir(req.current_user)
    strategy_store = TOMLStore(
        user_dir=user_dir,
        filename="strategies.toml",
        default_factory=dict,
    )
    current_strategy = await strategy_store.read()
    weights = current_strategy.get("reminder_weights", {})
    delta = 0.1 if safe_action == "accept" else -0.1
    new_weight = weights.get(actual_type, 0.5) + delta
    weights[actual_type] = max(0.1, min(1.0, new_weight))
    await strategy_store.update("reminder_weights", weights)

    return FeedbackResponse(status="success")
```

- [ ] **步骤 2：lint/type 检查**

```bash
uv run ruff check --fix app/api/routes/feedback.py && uv run ruff format app/api/routes/feedback.py && uv run ty check app/api/routes/feedback.py
```

- [ ] **步骤 3：Commit**

```bash
git add app/api/routes/feedback.py
git commit -m "feat(api): add feedback route (POST /api/feedback)"
```

---

### 任务 6：创建 reminders 路由

**文件：**
- 创建：`app/api/routes/reminders.py`
- 参考实现：`app/api/resolvers/mutation.py` 中 pollPendingReminders、cancelPendingReminder、getPendingReminders

- [ ] **步骤 1：编写 `app/api/routes/reminders.py`**

```python
"""待触发提醒路由."""

from datetime import UTC, datetime

from fastapi import APIRouter

from app.agents.pending import PendingReminderManager
from app.api.schemas import (
    PendingReminderResponse,
    PollRemindersRequest,
    PollRemindersResponse,
    TriggeredReminderResponse,
)
from app.config import user_data_dir

router = APIRouter()


@router.post("/reminders/poll", response_model=PollRemindersResponse)
async def poll_pending_reminders(req: PollRemindersRequest) -> PollRemindersResponse:
    """车机端轮询待触发提醒."""
    pm = PendingReminderManager(user_data_dir(req.current_user))
    ctx = req.context.model_dump() if req.context else {}
    triggered = await pm.poll(ctx)
    return PollRemindersResponse(
        triggered=[
            TriggeredReminderResponse(
                id=r["id"],
                event_id=r.get("event_id", ""),
                content=r.get("content", {}),
                triggered_at=datetime.now(UTC).isoformat(),
            )
            for r in triggered
        ]
    )


@router.delete("/reminders/{reminder_id}")
async def cancel_pending_reminder(
    reminder_id: str,
    current_user: str = "default",
) -> dict[str, bool]:
    """取消指定 ID 的待触发提醒."""
    pm = PendingReminderManager(user_data_dir(current_user))
    await pm.cancel(reminder_id)
    return {"success": True}


@router.get("/reminders", response_model=list[PendingReminderResponse])
async def get_pending_reminders(
    current_user: str = "default",
) -> list[PendingReminderResponse]:
    """获取当前用户所有待触发提醒列表."""
    pm = PendingReminderManager(user_data_dir(current_user))
    pending = await pm.list_pending()
    return [
        PendingReminderResponse(
            id=r["id"],
            event_id=r.get("event_id", ""),
            trigger_type=r.get("trigger_type", ""),
            trigger_text=r.get("trigger_text", ""),
            status=r.get("status", ""),
            created_at=r.get("created_at", ""),
        )
        for r in pending
    ]
```

- [ ] **步骤 2：lint/type 检查**

```bash
uv run ruff check --fix app/api/routes/reminders.py && uv run ruff format app/api/routes/reminders.py && uv run ty check app/api/routes/reminders.py
```

- [ ] **步骤 3：Commit**

```bash
git add app/api/routes/reminders.py
git commit -m "feat(api): add reminders routes (poll, cancel, list)"
```

---

### 任务 7：创建 sessions 路由

**文件：**
- 创建：`app/api/routes/sessions.py`
- 参考实现：`app/api/resolvers/mutation.py` close_session

- [ ] **步骤 1：编写 `app/api/routes/sessions.py`**

```python
"""会话管理路由."""

from fastapi import APIRouter

from app.agents.conversation import _conversation_manager

router = APIRouter()


@router.post("/sessions/{session_id}/close")
async def close_session(
    session_id: str,
    current_user: str = "default",
) -> dict[str, bool]:
    """关闭指定会话（校验用户归属）."""
    ok = _conversation_manager.close(session_id, user_id=current_user)
    return {"success": ok}
```

- [ ] **步骤 2：lint/type 检查**

```bash
uv run ruff check --fix app/api/routes/sessions.py && uv run ruff format app/api/routes/sessions.py && uv run ty check app/api/routes/sessions.py
```

- [ ] **步骤 3：Commit**

```bash
git add app/api/routes/sessions.py
git commit -m "feat(api): add sessions route (POST /api/sessions/{id}/close)"
```

---

### 任务 8：创建 routes/__init__.py 汇总注册

**文件：**
- 创建：`app/api/routes/__init__.py`

- [ ] **步骤 1：编写 `app/api/routes/__init__.py`**

```python
"""REST API 路由汇总."""

from fastapi import APIRouter

from app.api.routes.data import router as data_router
from app.api.routes.feedback import router as feedback_router
from app.api.routes.presets import router as presets_router
from app.api.routes.query import router as query_router
from app.api.routes.reminders import router as reminders_router
from app.api.routes.sessions import router as sessions_router

api_router = APIRouter()
api_router.include_router(data_router, tags=["data"])
api_router.include_router(feedback_router, tags=["feedback"])
api_router.include_router(presets_router, tags=["presets"])
api_router.include_router(query_router, tags=["query"])
api_router.include_router(reminders_router, tags=["reminders"])
api_router.include_router(sessions_router, tags=["sessions"])
```

- [ ] **步骤 2：lint/type 检查**

```bash
uv run ruff check --fix app/api/routes/__init__.py && uv run ruff format app/api/routes/__init__.py && uv run ty check app/api/routes/__init__.py
```

- [ ] **步骤 3：Commit**

```bash
git add app/api/routes/__init__.py
git commit -m "feat(api): add routes package with all sub-routers"
```

---

### 任务 9：改写 main.py，删除 GraphQL 依赖

**文件：**
- 修改：`app/api/main.py`

- [ ] **步骤 1：改写 `app/api/main.py`**

删除所有 strawberry 相关 import 和 `_mount_graphql()` 函数，改用 REST 路由注册。

改写后完整文件：

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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.agents.conversation import _conversation_manager
from app.api.routes import api_router
from app.api.stream import router as stream_router
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
app.mount("/static", StaticFiles(directory=WEBUI_DIR), name="static")

app.include_router(api_router, prefix="/api")
app.include_router(stream_router)


@app.get("/")
async def root() -> FileResponse:
    """返回前端 WebUI 入口页面."""
    return FileResponse(WEBUI_DIR / "index.html")
```

- [ ] **步骤 2：lint/type 检查**

```bash
uv run ruff check --fix app/api/main.py && uv run ruff format app/api/main.py && uv run ty check app/api/main.py
```

- [ ] **步骤 3：Commit**

```bash
git add app/api/main.py
git commit -m "refactor(api): replace GraphQL mount with REST router registration"
```

---

### 任务 10：删除 GraphQL 残留文件

**文件：**
- 删除：`app/api/graphql_schema.py`
- 删除：`app/api/resolvers/converters.py`
- 删除：`app/api/resolvers/errors.py`
- 删除：`app/api/resolvers/mutation.py`
- 删除：`app/api/resolvers/query.py`
- 删除：`app/api/resolvers/__init__.py`

- [ ] **步骤 1：删除文件**

```bash
git rm app/api/graphql_schema.py app/api/resolvers/converters.py app/api/resolvers/errors.py app/api/resolvers/mutation.py app/api/resolvers/query.py app/api/resolvers/__init__.py
```

- [ ] **步骤 2：验证 pytest 仍可导入运行**

```bash
uv run pytest tests/ -x --tb=short -q
```

预期：可能有 `test_graphql.py` 失败（因路由已改），但无导入错误。

- [ ] **步骤 3：Commit**

```bash
git commit -m "refactor(api): remove GraphQL schema, resolvers, and converters"
```

---

### 任务 11：从 pyproject.toml 删除 strawberry-graphql 依赖

**文件：**
- 修改：`pyproject.toml`

- [ ] **步骤 1：删除依赖行**

从 `dependencies` 中删除 `strawberry-graphql[fastapi]>=0.312.2`。

- [ ] **步骤 2：更新 lockfile**

```bash
uv lock
```

- [ ] **步骤 3：验证安装和导入**

```bash
uv sync && python -c "from app.api.main import app; print('OK')"
```

预期：成功导入，无 strawberry 残留。

- [ ] **步骤 4：Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: remove strawberry-graphql dependency"
```

---

### 任务 12：改写 WebUI 前端

**文件：**
- 修改：`webui/app.js`

- [ ] **步骤 1：改写 `webui/app.js`**

将 `graphql()` helper 替换为 REST fetch 辅助函数，所有调用改为对应 REST 端点。字段名从 camelCase 改为 snake_case。

接口 + 思路：

1. 删 `graphql()` 函数。新增 `api(method, path, body?)` 辅助函数：
```javascript
async function api(method, path, body) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const resp = await fetch(path, opts);
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${resp.status}`);
    }
    return resp.json();
}
```

2. `loadPresets()` — `GET /api/presets?current_user=default`，响应字段已是 snake_case。响应中的 context 字段直接用，无需 GraphQL 嵌套选择。

3. `savePreset()` — `POST /api/presets`，body: `{ name, context, current_user }`。

4. `loadExperimentData()` — `GET /api/experiments`，响应 `{ strategies: [{ strategy, exact_match, field_f1, value_f1 }] }`。

5. `sendQuery()` — `POST /api/query`，body 复用 `ProcessQueryRequest` 格式（`query`, `memory_mode`, `context`, `current_user`）。响应 `{ result, event_id, stages }`。

6. `submitFeedback()` — `POST /api/feedback`，body: `{ event_id, action, memory_mode, current_user }`。

7. `loadHistory()` — `GET /api/history?limit=10&memory_mode=memory_bank&current_user=default`。响应 `[{ id, content, type, description, created_at }]`。

8. `getContextInput()` — 返回的对象字段从 camelCase 改为 snake_case：
   - `fatigueLevel` → `fatigue_level`
   - `speedKmh` → `speed_kmh`
   - `currentLocation` → `current_location`
   - `estimatedDelayMinutes` → `estimated_delay_minutes`
   - `congestionLevel` → `congestion_level`
   - `etaMinutes` → `eta_minutes`

9. `fillForm()` — 从 preset 对象读取 snake_case 字段，`d.fatigue_level`, `cl.speed_kmh`, `t.estimated_delay_minutes` 等。

- [ ] **步骤 2：手动验证**

启动服务 `uv run uvicorn app.api.main:app`，打开浏览器访问 WebUI，测试：
- 加载预设列表
- 保存预设
- 发送查询
- 提交反馈
- 加载历史

- [ ] **步骤 3：Commit**

```bash
git add webui/app.js
git commit -m "refactor(webui): replace GraphQL client with REST API calls"
```

---

### 任务 13：重写 API 测试

**文件：**
- 重写：`tests/api/test_graphql.py` → `tests/api/test_rest.py`

- [ ] **步骤 1：编写 `tests/api/test_rest.py`**

接口 + 思路：

1. `isolated_app` fixture 不变。
2. 删 `_graphql_query` helper。
3. 每个测试改用 `isolated_app.get(...)` / `isolated_app.post(...)` / `isolated_app.delete(...)` 直接调用 REST 端点。

映射：
- `test_experiment_report_removed` → 删（GraphQL 特有检查，不再适用）
- `test_scenario_presets_query` → `GET /api/presets`，断言 `resp.status_code == 200`，`resp.json()` 为 list
- `test_save_scenario_preset` → `POST /api/presets`，body `{ name, context: { scenario: "highway" }, current_user: "default" }`
- `test_delete_scenario_preset` → 先 POST 保存，再 `DELETE /api/presets/{id}`，断言 `{"success": true}`
- `test_delete_nonexistent_preset` → `DELETE /api/presets/nonexistent`，断言 `{"success": false}`
- `test_feedback_invalid_action` → `POST /api/feedback`，body `{ event_id: "x", action: "invalid" }`。注意：action 现在是 `Literal["accept", "ignore"]`，Pydantic 会返回 422。断言 `resp.status_code == 422`
- `test_feedback_success_updates_strategy_weight` → `POST /api/feedback`，body `{ event_id, action: "accept" }`，断言 `resp.status_code == 200`，权重检查逻辑不变
- `test_process_query_without_context` → `POST /api/query`，body `{ query: "...", memory_mode: "memory_bank" }`
- `test_process_query_with_context` → `POST /api/query`，body 带完整 context dict

- [ ] **步骤 2：删旧测试文件**

```bash
git rm tests/api/test_graphql.py
```

- [ ] **步骤 3：运行新测试**

```bash
uv run pytest tests/api/test_rest.py -v
```

预期：除 `test_feedback_success_updates_strategy_weight`（需 embedding）、`test_process_query_*`（需 integration）外，其余通过。

- [ ] **步骤 4：运行全量测试确认无回归**

```bash
uv run pytest tests/ -x --tb=short -q
```

- [ ] **步骤 5：Commit**

```bash
git add tests/api/test_rest.py tests/api/test_graphql.py
git commit -m "test(api): rewrite GraphQL tests as REST endpoint tests"
```

---

### 任务 14：最终验证与清理

- [ ] **步骤 1：全量 lint + format + type check**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```

预期：全部通过。

- [ ] **步骤 2：全量测试**

```bash
uv run pytest tests/ -v
```

预期：450 passed, 23 skipped（与基准一致）。

- [ ] **步骤 3：验证 GraphQL 端点已移除**

```bash
python -c "from app.api.main import app; routes = [r.path for r in app.routes]; print([r for r in routes if 'graphql' in r.lower()])"
```

预期：空列表。

- [ ] **步骤 4：验证 REST 端点可访问**

```bash
python -c "from app.api.main import app; routes = [r.path for r in app.routes]; print([r for r in routes if r.startswith('/api')])"
```

预期：列出所有 `/api/*` 路由。

- [ ] **步骤 5：检查 strawberry 残留引用**

```bash
rg "strawberry" app/ --include="*.py" -l
rg "graphql" app/ --include="*.py" -l
```

预期：零结果。

- [ ] **步骤 6：Commit（如有自动修复产生的变更）**

```bash
git add -A && git commit -m "chore: final cleanup after REST migration"
```
