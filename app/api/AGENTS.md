# API 层

`app/api/` — FastAPI v1 REST + WebSocket。

## v1 端点

所有端点前缀 `/api/v1`。用户身份由 `X-User-Id` header 注入（默认 `default`）。

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

Schema 定义于 `app/api/schemas.py` + `app/schemas/query.py`。

## WebSocket

`WS /api/v1/ws?user_id=xxx`。`ws_manager`（`v1/ws_manager.py`）按 `user_id` 管理连接列表，支持广播。

消息格式（统一用 `payload` 键）：
- 客户端→服务端：`{"type": "query", "payload": {"query": "...", "context": {...}, "session_id": "..."}}`
- 服务端→客户端：`{"type": "stage_start"|"context_done"|"decision"|"done"|"error"|"reminder", "payload": {...}}`
- 心跳：客户端每30s发 `{"type": "ping"}`，服务端返 `{"type": "pong", "payload": {}}`；服务端 60s 读超时（`_HEARTBEAT_TIMEOUT = 60.0`），超时则断连
- 非法 JSON：返回 `{"type": "error", "payload": {"code": "INVALID_JSON", "message": "Malformed JSON"}}`，不断连
- payload 非 object：返回 `{"code": "INVALID_PAYLOAD", "message": "Payload must be an object"}`
- 未知 type：返回 `{"code": "INVALID_MESSAGE", "message": "Unknown type: ..."}`
- 查询初始化/处理失败：返回 `{"code": "QUERY_FAILED", "message": "..."}`

## 错误处理

`app/api/errors.py`。`AppError` 继承 `HTTPException`，统一错误信封 `{"error": {"code": "...", "message": "..."}}`。

| AppErrorCode | HTTP | 场景 |
|---|---|---|
| NOT_FOUND | 404 | 资源不存在 |
| INVALID_INPUT | 422 | 请求参数不合法 |
| STORAGE_ERROR | 503 | 存储不可用 |
| INTERNAL_ERROR | 500 | 未预期异常 |

`safe_memory_call` 包装多数存储/记忆调用。例外：`get_memory_module()` 在 `query.py`、`feedback.py`、`data.py` 中使用裸 try/except 而非 `safe_memory_call`。`ChatModelUnavailableError` → 500。

## 中间件

`UserIdentityMiddleware`：从 `X-User-Id` header 提取用户 ID，注入 `request.state.user_id`。仅处理 HTTP，WS 端点直接读 `ws.headers`。

## 服务入口

**启动**：`uv run uvicorn app.api.main:app`

**Lifespan**：
- 启动：`init_storage()` + 后台每300s清理过期会话 + `ProactiveScheduler` 初始化（默认用户） + `_init_voice_if_available(sched)` 初始化 VoicePipeline + VoiceRecorder（失败静默降级）
- 运行：ProactiveScheduler 每15s轮询 ContextMonitor/MemoryScanner/TriggerEvaluator，触发 `AgentWorkflow.proactive_run()`；VoicePipeline 转录回调推送至 scheduler
- 关闭：`_stop_voice()` 停止录音流水线 + `ProactiveScheduler.stop()` + `MemoryModule.close()` FAISS落盘 + `close_client_cache()`

**CORS**：开发用 `allow_origins=["*"]`，部署前须收敛。

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
