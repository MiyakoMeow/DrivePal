# API层

`app/api/` —— FastAPI REST API，挂载于 `/api` 前缀。

## 端点一览

| 方法 | 路径 | 用途 | 请求/响应 Schema |
|------|------|------|------------------|
| POST | `/api/query` | 处理用户查询，返回完整工作流结果 | `ProcessQueryRequest` → `ProcessQueryResponse` |
| POST | `/api/query/stream` | SSE 流式返回各阶段结果 | `ProcessQueryRequest` → `text/event-stream` |
| POST | `/api/feedback` | 提交用户反馈（accept/ignore） | `FeedbackRequest` → `FeedbackResponse` |
| GET | `/api/history` | 查询历史记忆事件 | query: `limit`, `current_user` → `list[MemoryEventResponse]` |
| GET | `/api/export` | 导出当前用户全量文本数据 | query: `current_user` → `ExportDataResponse` |
| DELETE | `/api/data` | 删除当前用户全量数据 | query: `current_user` → `{success: bool}` |
| GET | `/api/experiments` | 查询五策略实验结果对比 | → `ExperimentResultsResponse` |
| GET | `/api/presets` | 查询所有场景预设 | query: `current_user` → `list[ScenarioPresetResponse]` |
| POST | `/api/presets` | 保存场景预设 | `SavePresetRequest` → `ScenarioPresetResponse` |
| DELETE | `/api/presets/{preset_id}` | 删除场景预设 | → `{success: bool}` |
| POST | `/api/reminders/poll` | 车机端轮询待触发提醒 | `PollRemindersRequest` → `PollRemindersResponse` |
| DELETE | `/api/reminders/{reminder_id}` | 取消待触发提醒 | → `{success: bool}` |
| GET | `/api/reminders` | 获取待触发提醒列表 | query: `current_user` → `list[PendingReminderResponse]` |
| POST | `/api/sessions/{session_id}/close` | 关闭指定会话 | query: `current_user` → `{success: bool}` |

## 请求/响应 Schema

定义于 `app/api/schemas.py`。查询端点额外使用 `app/schemas/query.py`。

### 查询

- **ProcessQueryRequest** (`app/schemas/query.py`): `query` (str), `context` (dict | None), `current_user` (str, 默认 "default"), `session_id` (str | None)
- **ProcessQueryResponse**: `result` (str), `event_id` (str | None), `stages` (dict | None)

### 反馈

- **FeedbackRequest**: `event_id` (str), `action` (Literal["accept", "ignore"]), `modified_content` (str | None), `current_user` (str)
- **FeedbackResponse**: `status` (str)

### 预设

- **SavePresetRequest**: `name` (str), `context` (DrivingContext), `current_user` (str)
- **ScenarioPresetResponse**: `id`, `name`, `context` (DrivingContext), `created_at`

### 数据

- **MemoryEventResponse**: `id`, `content`, `type`, `description`, `created_at`
- **ExportDataResponse**: `files` (dict[str, str])
- **ExperimentResultResponse**: `strategy`, `exact_match`, `field_f1`, `value_f1`
- **ExperimentResultsResponse**: `strategies` (list[ExperimentResultResponse])

### 提醒

- **PollRemindersRequest**: `current_user`, `context` (DrivingContext | None)
- **TriggeredReminderResponse**: `id`, `event_id`, `content` (dict), `triggered_at`
- **PollRemindersResponse**: `triggered` (list[TriggeredReminderResponse])
- **PendingReminderResponse**: `id`, `event_id`, `trigger_type`, `trigger_text`, `status`, `created_at`

## SSE 流式端点

`POST /query/stream` — `app/api/stream.py`。`Content-Type: text/event-stream`。

逐阶段推送事件：

| 事件 | 触发时机 | data 内容 |
|------|---------|----------|
| `stage_start` | 每阶段开始 | `{stage: "context" \| "joint_decision" \| "execution"}` |
| `context_done` | Context 阶段完成 | `{context: {...}}` |
| `decision` | JointDecision 阶段完成 | `{should_remind: bool, task_type: string}` |
| `done` | Execution 完成 | `_build_done_data()`：status=delivered/pending/suppressed |
| `error` | 任一阶段失败 | `{code: string, message: string}` |

快捷指令命中时跳过中间事件，直接 yield done/error。

## 错误处理

### safe_memory_call

`app/api/errors.py`。包装记忆系统调用，异常统一转 HTTPException：

| 异常类型 | HTTP 状态码 | 触发条件 |
|---------|------------|---------|
| OSError | 503 | 存储服务不可用 |
| ValueError | 422 | 数据校验失败 |
| 其余 | 500 | 内部错误 |

### 路由级异常捕获

`app/api/routes/query.py` 额外捕获 `ChatModelUnavailableError` → 503。

## 服务入口与生命周期

**入口：** `uv run uvicorn app.api.main:app`

**Lifespan 事件：**
- **启动：** `init_storage()` 初始化数据目录（首次运行迁移旧结构至 `data/users/default/`）；启动 `_periodic_cleanup` 后台任务每 300s 清理过期会话
- **关闭：** `MemoryModule.close()` 关闭 MemoryBank（FAISS 落盘 + 后台任务取消等待）；`close_client_cache()` 关闭 Chat 客户端缓存

**中间件：** CORS（`allow_origins=["*"]`，开发用）

**路由注册：** `app/api/routes/__init__.py`。6 个子路由模块（data/feedback/presets/query/reminders/sessions），通过 `APIRouter` 汇总为 `api_router`。

**静态文件：** `/static` 挂载 WebUI 目录，`GET /` 返回 `index.html`

## 反馈学习机制

1. **权重更新**：`POST /api/feedback` 接受（accept）时对应类型权重 +0.1（上限 1.0），忽略（ignore）时 -0.1（下限 0.1），新类型初始 0.5。权重存入 `strategies.toml` 的 `reminder_weights`
2. **权重注入**：权重经 `_format_preference_hint()` 转为自然语言提示，通过 system prompt 的 `{preference_hint}` 占位符和用户 prompt 正文两路注入 JointDecision Agent（权重 ≥ 0.6 强引导，≥ 0.5 弱引导，低于 0.5 不提示）
3. **注入时机**：JointDecision Agent 调用前，prompt 中注入偏好提示
4. **交互顺序**：规则引擎先处理硬约束 → JointDecision Agent 语义推理（受偏好影响）→ `postprocess_decision()` 规则后处理（allowed_channels 过滤、非紧急降级等）
