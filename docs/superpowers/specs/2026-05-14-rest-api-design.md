# GraphQL → REST 全量替换设计规格

**日期：** 2026-05-14
**工作树：** `.worktrees/refactor/rest-api`（分支 `refactor/rest-api`）
**状态：** 待实现

## 动机

当前项目使用 Strawberry GraphQL（code-first）作为 API 层，但未使用任何 GraphQL 独有特性：

- 0 个 Subscription（实时推送已用 SSE 纯 REST 端点）
- 无字段选择优化（WebUI 每次请求相同字段）
- 无 Batching、Federation、自定义 Directive

GraphQL 在此项目中仅带来额外复杂度：
- Pydantic ↔ Strawberry 双重类型维护（`graphql_schema.py` 311 行与 `schemas/context.py` 高度重复）
- `converters.py`（78 行）纯桥接代码
- `strawberry-graphql` 及其传递依赖

## 方案

删除 Strawberry GraphQL，13 个操作全部转为 FastAPI 原生 REST 路由，Pydantic 模型直接作 request/response schema。

## API 路由映射

| # | GraphQL 操作 | REST 端点 | 方法 | Request | Response |
|---|---|---|---|---|---|
| 1 | `history` query | `GET /api/history` | GET | query: `limit`, `memory_mode`, `current_user` | `list[MemoryEventResponse]` |
| 2 | `scenarioPresets` query | `GET /api/presets` | GET | query: `current_user` | `list[ScenarioPresetResponse]` |
| 3 | `experimentResults` query | `GET /api/experiments` | GET | 无 | `ExperimentResultsResponse` |
| 4 | `processQuery` mutation | `POST /api/query` | POST | body: `ProcessQueryRequest`（已有） | `ProcessQueryResponse` |
| 5 | `submitFeedback` mutation | `POST /api/feedback` | POST | body: `FeedbackRequest` | `FeedbackResponse` |
| 6 | `saveScenarioPreset` mutation | `POST /api/presets` | POST | body: `SavePresetRequest` | `ScenarioPresetResponse` |
| 7 | `deleteScenarioPreset` mutation | `DELETE /api/presets/{preset_id}` | DELETE | query: `current_user` | `{"success": bool}` |
| 8 | `exportData` mutation | `GET /api/export` | GET | query: `current_user` | `ExportDataResponse` |
| 9 | `deleteAllData` mutation | `DELETE /api/data` | DELETE | query: `current_user` | `{"success": bool}` |
| 10 | `pollPendingReminders` mutation | `POST /api/reminders/poll` | POST | body: `PollRemindersRequest` | `PollRemindersResponse` |
| 11 | `cancelPendingReminder` mutation | `DELETE /api/reminders/{reminder_id}` | DELETE | query: `current_user` | `{"success": bool}` |
| 12 | `getPendingReminders` mutation | `GET /api/reminders` | GET | query: `current_user` | `list[PendingReminderResponse]` |
| 13 | `closeSession` mutation | `POST /api/sessions/{session_id}/close` | POST | query: `current_user` | `{"success": bool}` |

**不变：** `POST /query/stream`（SSE 端点）路径不变，已无 GraphQL 依赖。

**设计决策：**
- `pollPendingReminders` 用 POST：含复杂 request body（DrivingContext），不适合 query params
- `exportData` 用 GET：幂等读取操作
- `closeSession` 用 POST：非幂等状态变更
- REST 端字段命名统一用 snake_case（FastAPI 默认），前端跟随

## Request/Response Schema

新增 Pydantic 模型定义于 `app/api/schemas.py`，复用 `app/schemas/context.py` 已有模型。

### ProcessQueryRequest（已存在于 `app/schemas/query.py`，直接复用）

```python
class ProcessQueryRequest(BaseModel):
    query: str
    memory_mode: MemoryMode = MemoryMode.MEMORY_BANK
    context: dict | None = None
    current_user: str = "default"
    session_id: str | None = None
```

### ProcessQueryResponse

```python
class ProcessQueryResponse(BaseModel):
    result: str
    event_id: str | None = None
    stages: dict | None = None  # {context, task, decision, execution}
```

### FeedbackRequest

```python
class FeedbackRequest(BaseModel):
    event_id: str
    action: Literal["accept", "ignore"]
    memory_mode: MemoryMode = MemoryMode.MEMORY_BANK
    modified_content: str | None = None
    current_user: str = "default"
```

### FeedbackResponse

```python
class FeedbackResponse(BaseModel):
    status: str
```

### SavePresetRequest

```python
class SavePresetRequest(BaseModel):
    name: str
    context: DrivingContext  # 复用 app/schemas/context.py
    current_user: str = "default"
```

### ScenarioPresetResponse

```python
class ScenarioPresetResponse(BaseModel):
    id: str
    name: str
    context: DrivingContext
    created_at: str
```

### MemoryEventResponse

```python
class MemoryEventResponse(BaseModel):
    id: str
    content: str
    type: str
    description: str
    created_at: str
```

### ExportDataResponse

```python
class ExportDataResponse(BaseModel):
    files: dict[str, str]
```

### ExperimentResultResponse / ExperimentResultsResponse

```python
class ExperimentResultResponse(BaseModel):
    strategy: str
    exact_match: float
    field_f1: float
    value_f1: float

class ExperimentResultsResponse(BaseModel):
    strategies: list[ExperimentResultResponse]
```

### PollRemindersRequest

```python
class PollRemindersRequest(BaseModel):
    current_user: str = "default"
    context: DrivingContext | None = None
```

### PollRemindersResponse

```python
class TriggeredReminderResponse(BaseModel):
    id: str
    event_id: str
    content: dict
    triggered_at: str

class PollRemindersResponse(BaseModel):
    triggered: list[TriggeredReminderResponse]
```

### PendingReminderResponse

```python
class PendingReminderResponse(BaseModel):
    id: str
    event_id: str
    trigger_type: str
    trigger_text: str
    status: str
    created_at: str
```

## 错误处理

`GraphQLError` → FastAPI `HTTPException`：

| 旧异常 | 新异常 | HTTP 状态码 |
|---|---|---|
| `InternalServerError` | `HTTPException(status_code=500)` | 500 |
| `GraphQLInvalidActionError` | `HTTPException(status_code=422, detail=...)` | 422 |
| `GraphQLEventNotFoundError` | `HTTPException(status_code=404, detail=...)` | 404 |
| `ChatModelUnavailableError` | `HTTPException(status_code=503, detail=...)` | 503 |

`safe_memory_call`（提取至 `app/api/errors.py`）保留逻辑，异常类型改为 `HTTPException`。

## 文件变更

### 删除

| 文件 | 行数 | 理由 |
|---|---|---|
| `app/api/graphql_schema.py` | 311 | Strawberry 类型定义全部废弃 |
| `app/api/resolvers/converters.py` | 78 | Pydantic↔Strawberry 桥接不再需要 |
| `app/api/resolvers/errors.py` | 27 | GraphQLError 子类不再使用 |
| `app/api/resolvers/__init__.py` | 1 | 空标记文件 |
| `app/api/resolvers/mutation.py` | 329 | 拆入 routes/ |
| `app/api/resolvers/query.py` | 89 | 拆入 routes/ |

### 新建

| 文件 | 估算行数 | 内容 |
|---|---|---|
| `app/api/schemas.py` | ~60 | REST 专用 request/response Pydantic 模型 |
| `app/api/routes/__init__.py` | ~10 | 汇总注册所有路由 |
| `app/api/routes/query.py` | ~50 | `POST /api/query` |
| `app/api/routes/feedback.py` | ~50 | `POST /api/feedback` |
| `app/api/routes/presets.py` | ~40 | `GET/POST/DELETE /api/presets` |
| `app/api/routes/data.py` | ~60 | `GET /api/history`、`GET /api/export`、`DELETE /api/data`、`GET /api/experiments` |
| `app/api/routes/reminders.py` | ~60 | `GET/POST/DELETE /api/reminders` |
| `app/api/routes/sessions.py` | ~15 | `POST /api/sessions/{session_id}/close` |

### 修改

| 文件 | 变更 |
|---|---|
| `app/api/main.py` | 删 `_mount_graphql()`，改为 `include_router(routes_router, prefix="/api")` |
| `app/api/stream.py` | 无改动 |
| `webui/app.js` | GraphQL fetch → REST fetch（机械改写） |
| `pyproject.toml` | 删 `strawberry-graphql[fastapi]` |
| `tests/api/test_graphql.py` | 重写为 REST 测试 |

### 不动

| 文件 | 理由 |
|---|---|
| `app/schemas/context.py` | Pydantic 模型直接复用 |
| `app/schemas/query.py` | `ProcessQueryRequest` 直接复用 |
| `app/api/stream.py` | 已是纯 REST，无 GraphQL 依赖 |
| `app/agents/*` | 无 API 层耦合 |
| `app/memory/*` | 无 API 层耦合 |
| `app/storage/*` | 无 API 层耦合 |

## 净代码量

- 删除：~835 行
- 新增：~345 行
- **净减：~490 行**

## 依赖变更

`pyproject.toml` 删除：
- `strawberry-graphql[fastapi]>=0.312.2`

传递依赖自动移除：`graphql-core`、`graphql-relay` 等。

## WebUI 改写要点

`webui/app.js` 的 `graphql()` helper 改为 `rest()` helper。具体映射：

| GraphQL 调用 | REST 调用 |
|---|---|
| `graphql({processQuery: ...})` | `POST /api/query` |
| `graphql({submitFeedback: ...})` | `POST /api/feedback` |
| `graphql({scenarioPresets: ...})` | `GET /api/presets` |
| `graphql({saveScenarioPreset: ...})` | `POST /api/presets` |
| `graphql({history: ...})` | `GET /api/history` |
| `graphql({experimentResults: ...})` | `GET /api/experiments` |

字段命名从 camelCase 改为 snake_case，前端 JS 对象属性跟随。

## 不涉及

- 不修改 agents/memory/storage 内部逻辑
- 不修改 SSE stream 端点
- 不修改 `app/schemas/context.py` 的 Pydantic 模型
- 不引入新的认证/授权机制
- 不修改数据存储格式

## 未解决问题

无。
