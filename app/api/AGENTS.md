# API 层

`app/api/` — FastAPI v1 REST + WebSocket。用户身份由 `X-User-Id` header 注入（默认 `default`）。

## 组件

| 文件 | 职责 |
|------|------|
| `main.py` | FastAPI 应用入口、lifespan、CORS、静态文件 |
| `v1/query.py` | `POST /api/v1/query` 处理查询，返完整工作流结果 |
| `v1/ws.py` | WebSocket 长连接（流式查询 + 心跳） |
| `v1/ws_manager.py` | 按 `user_id` 管理 WS 连接，支持广播 |
| `v1/feedback.py` | `POST /api/v1/feedback` 提交反馈 |
| `v1/presets.py` | 场景预设增删查 |
| `v1/data.py` | 历史查询、导出、数据删除、实验结果对比 |
| `v1/reminders.py` | 提醒列表获取与取消 |
| `v1/sessions.py` | 会话管理（关闭） |
| `v1/voice.py` | `GET /api/v1/voice/status`、`POST /start|stop`、`GET|PUT /config`、`GET /transcriptions|devices` |
| `schemas.py` | Pydantic 请求/响应模型 |
| `errors.py` | 异常体系边界、AppErrorCode→HTTP 映射 |
| `middleware.py` | `UserIdentityMiddleware` |

## v1 端点

所有端点前缀 `/api/v1`。

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/api/v1/query` | 处理查询，返完整工作流结果 |
| WS | `/api/v1/ws` | WebSocket 长连接（流式查询 + 心跳） |
| POST | `/api/v1/feedback` | 提交反馈(accept/ignore/snooze/modify) |
| GET | `/api/v1/presets` | 查询场景预设 |
| POST | `/api/v1/presets` | 保存场景预设 |
| DELETE | `/api/v1/presets/{id}` | 删除预设 |
| GET | `/api/v1/history` | 查询历史记忆事件（`?limit=N`, 默认10, 1–100） |
| GET | `/api/v1/export` | 导出当前用户文本数据（`?export_type=events\|settings\|all`，排除 `memorybank/` 目录） |
| DELETE | `/api/v1/data` | 删除当前用户全量数据 |
| GET | `/api/v1/experiments` | 查询实验结果对比（系统级，非 per-user） |
| GET | `/api/v1/reminders` | 获取待触发提醒列表 |
| DELETE | `/api/v1/reminders/{id}` | 取消提醒 |
| POST | `/api/v1/sessions/{id}/close` | 关闭会话（校验用户归属） |
| GET | `/api/v1/voice/status` | 语音流水线运行状态（enabled/running/vad_status/config） |
| POST | `/api/v1/voice/start` | 开启录音（已运行返 409，禁用返 400） |
| POST | `/api/v1/voice/stop` | 停止录音 |
| GET | `/api/v1/voice/config` | 当前配置（device_index/vad_mode 等） |
| PUT | `/api/v1/voice/config` | 热更新配置（无效值返 400） |
| GET | `/api/v1/voice/transcriptions` | 转录历史（`?limit=N`，默认 50，`<1` 返空） |
| GET | `/api/v1/voice/devices` | 可用麦克风设备列表 |

Schema 代码见 `app/api/schemas.py` + `app/schemas/query.py` + `app/schemas/context.py`，字段说明见下方"数据模型"节。

### WebSocket

`WS /api/v1/ws?user_id=xxx`。`ws_manager`（`v1/ws_manager.py`）按 `user_id` 管理连接列表，支持广播。

消息格式（统一用 `payload` 键）：
- 客户端→服务端：`{"type": "query", "payload": {"query": "...", "context": {...}, "session_id": "..."}}`
- 服务端→客户端：`{"type": "stage_start"|"context_done"|"decision"|"done"|"error"|"reminder", "payload": {...}}`
- 心跳：客户端每30s发 `{"type": "ping"}`，服务端返 `{"type": "pong", "payload": {}}`；服务端 60s 读超时（`_HEARTBEAT_TIMEOUT = 60.0`），超时则断连
- 非法 JSON：返回 `{"type": "error", "payload": {"code": "INVALID_JSON", "message": "Malformed JSON"}}`，不断连
- payload 非 object：返回 `{"type": "error", "payload": {"code": "INVALID_PAYLOAD", "message": "Payload must be an object"}}`
- 未知 type：返回 `{"type": "error", "payload": {"code": "INVALID_MESSAGE", "message": "Unknown type: ..."}}`
- 查询初始化/处理失败：返回 `{"type": "error", "payload": {"code": "QUERY_FAILED", "message": "..."}}`

## 数据模型

### 驾驶上下文 (`app/schemas/context.py`)

- **DriverState**: emotion(neutral/anxious/fatigued/calm/angry), workload(low/normal/high/overloaded), fatigue_level(0~1)
- **GeoLocation**: latitude(ge=-90,le=90), longitude(ge=-180,le=180), address, speed_kmh(ge=0)
- **SpatioTemporalContext**: current_location, destination, eta_minutes(ge=0, null允许), heading(0~360, null允许)
- **TrafficCondition**: congestion_level(smooth/slow/congested/blocked), incidents(list[str]), estimated_delay_minutes(ge=0)
- **DrivingContext**: driver + spatial + traffic + scenario(parked/city_driving/highway/traffic_jam) + passengers
- **ScenarioPreset**: id(uuid hex[:12]), name, context, created_at

### 查询Schema (`query.py`)

- **ProcessQueryRequest**: query, context(DrivingContext|None), session_id
端点实际响应为 `ProcessQueryResponse`（`app/api/schemas.py:14`）：result, event_id, stages（WorkflowStages dict）。`ProcessQueryResult`（`app/schemas/query.py:24`）为内部工作流结果模型，非端点直返。

## 异常处理

`app/api/errors.py` — 异常体系之最终边界。

### AppErrorCode → HTTP

| Code | HTTP | 场景 |
|------|------|------|
| NOT_FOUND | 404 | 资源不存在 |
| INVALID_INPUT | 422 | 参数不合法 |
| STORAGE_ERROR | 503 | 存储不可用 |
| SERVICE_UNAVAILABLE | 503 | 模型/工作流不可用 |
| INTERNAL_ERROR | 500 | 未预期异常 |

### safe_call() 映射

统一包装存储/记忆/工作流调用：

| 源异常 | HTTP | 响应消息 |
|--------|------|---------|
| `TransientError` | 503 | Service temporarily unavailable |
| `FatalError` | 500 | Internal storage error |
| `ToolExecutionError` | 500 | Tool execution failed |
| `WorkflowError` | 503 | Service temporarily unavailable |
| `BaseAppError`(非HTTP) | 500 | Internal error |
| `BaseAppError`(含API) | 直抛 | 原样 |
| `ValueError` | 422 | Invalid request data |
| `OSError` | 503 | Service temporarily unavailable |
| 其余 | 500 | Internal server error |

日志 `logger.exception()` 持久化，消息泛化防泄露。

### 响应信封

```json
{"error": {"code": "STORAGE_ERROR", "message": "Service temporarily unavailable"}}
```

Pydantic 校验失败 → `validation_error_handler` → `422 INVALID_INPUT`。

## 中间件

`UserIdentityMiddleware`：从 `X-User-Id` header 提取用户 ID，注入 `request.state.user_id`。仅处理 HTTP。WS 端点按优先级：`query_params["user_id"]` > `x-user-id` header > 默认 `"default"`。

## 服务入口

**启动**：`uv run uvicorn app.api.main:app`

**Lifespan**：
- 启动：`init_storage()` + 后台每300s清理过期会话 + `ProactiveScheduler` 初始化（默认用户） + `VoiceService.start(sched)` 初始化语音流水线（配置 enabled=False 时静默跳过，ASR/pyaudio 缺失时降级）
- 运行：ProactiveScheduler 每15s轮询 ContextMonitor/MemoryScanner/TriggerEvaluator，触发 `AgentWorkflow.proactive_run()`；VoiceService 转录回调推送至 scheduler
- 关闭：`VoiceService.stop()` 停止录音流水线 + `ProactiveScheduler.stop()` + `close_memory_module()` FAISS落盘 + `close_client_cache()`

**CORS**：`origins` 由 `DRIVEPAL_CORS_ORIGINS` 环境变量配置（默认 `*`，逗号分隔多值）。wildcard 时禁用 credentials（`allow_credentials=False`），非 wildcard 时启用。

**静态文件**：`/static` → WebUI，`GET /` → index.html。静态路径由 `WEBUI_DIR` 环境变量覆盖（默认 `webui/`）。

## 反馈学习

`POST /api/v1/feedback` 更新 `strategies.toml` 的 `reminder_weights`：

| action | 权重变化 |
|--------|---------|
| accept | +0.1（上限1.0） |
| ignore | -0.1（下限0.1） |
| snooze | 创建5分钟延迟提醒（验证事件存在） |
| modify | +0.05（用户微调偏好） |

权重注入：`_format_preference_hint()` → system prompt + 用户 prompt → JointDecision。
≥0.6 强引导，≥0.5 弱引导，<0.5 不提示。
