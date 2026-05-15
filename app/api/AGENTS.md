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
| GET | `/api/v1/history` | 查询历史记忆事件（`?limit=N`, 1–100） |
| GET | `/api/v1/export` | 导出当前用户文本数据（`?export_type=events\|settings\|all`） |
| DELETE | `/api/v1/data` | 删除当前用户全量数据 |
| GET | `/api/v1/experiments` | 查询实验结果对比（系统级，非 per-user） |
| GET | `/api/v1/reminders` | 获取待触发提醒列表 |
| DELETE | `/api/v1/reminders/{id}` | 取消提醒 |
| POST | `/api/v1/sessions/{id}/close` | 关闭会话（校验用户归属） |

Schema 定义于 `app/api/schemas.py` + `app/schemas/query.py`。

## WebSocket

`WS /api/v1/ws`。`ws_manager`（`v1/ws_manager.py`）按 `user_id` 管理连接列表，支持广播。

消息格式（统一用 `payload` 键）：
- 客户端→服务端：`{"type": "query", "payload": {"query": "...", "context": {...}, "session_id": "..."}}`
- 服务端→客户端：`{"type": "stage_start"|"context_done"|"decision"|"done"|"error"|"reminder", "payload": {...}}`
- 心跳：客户端每30s发 `{"type": "ping"}`，服务端返 `{"type": "pong", "payload": {}}`
- 非法 JSON：返回 `{"type": "error", "payload": {"code": "INVALID_JSON", "message": "Malformed JSON"}}`，不断连

## 错误处理

`app/api/errors.py`。`AppError` 继承 `HTTPException`，统一错误信封 `{"error": {"code": "...", "message": "..."}}`。

| AppErrorCode | HTTP | 场景 |
|---|---|---|
| NOT_FOUND | 404 | 资源不存在 |
| INVALID_INPUT | 422 | 请求参数不合法 |
| STORAGE_ERROR | 503 | 存储不可用 |
| INTERNAL_ERROR | 500 | 未预期异常 |

`safe_memory_call` 包装所有存储/记忆调用。`ChatModelUnavailableError` → 503。

## 中间件

`UserIdentityMiddleware`：从 `X-User-Id` header 提取用户 ID，注入 `request.state.user_id`。仅处理 HTTP，WS 端点直接读 `ws.headers`。

## 服务入口

**启动**：`uv run uvicorn app.api.main:app`

**Lifespan**：
- 启动：`init_storage()` + 后台每300s清理过期会话
- 关闭：`MemoryModule.close()` FAISS落盘 + `close_client_cache()`

**静态文件**：`/static` → WebUI，`GET /` → index.html

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
