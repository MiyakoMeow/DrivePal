# API 层与 WebUI 优化设计

日期：2026-05-15
状态：已批准

## 概要

对 DrivePal 的 API 层与前端 WebUI 进行全面优化，不保证向后兼容。

## 1. API 层重构

### 1.1 路径版本化

所有 REST 端点移至 `/api/v1/` 前缀。

| 方法 | 旧路径 | 新路径 |
|------|--------|--------|
| POST | `/api/query` | `/api/v1/query` |
| POST | `/query/stream` | 删除（由 WS 取代） |
| POST | `/api/feedback` | `/api/v1/feedback` |
| GET | `/api/history` | `/api/v1/history` |
| GET | `/api/export` | `/api/v1/export` |
| DELETE | `/api/data` | `/api/v1/data` |
| GET | `/api/experiments` | `/api/v1/experiments` |
| GET/POST/DELETE | `/api/presets` | `/api/v1/presets` |
| GET/DELETE | `/api/reminders` | `/api/v1/reminders` |
| GET | `/api/sessions/{id}/close` | `/api/v1/sessions/{id}/close` |

静态文件 `/static/*` 和根路径 `/` → `index.html` 不变。

### 1.2 用户鉴权：X-User-Id Header

新增 `middleware.py`，从 `X-User-Id` HTTP header 提取用户 ID，注入 `request.state.user_id`。

- 所有路由从 `request.state` 读取用户 ID，不再接收 `current_user` 参数
- 缺失时默认 `"default"`（与现行为一致）
- 无密码/Token 校验，毕设范围内够用
- `user_data_dir()` 的路径遍历校验保留

### 1.3 统一错误信封

所有错误返回统一格式：

```json
{"error": {"code": "NOT_FOUND", "message": "事件不存在"}}
```

标准 HTTP 状态码继续使用（404/422/500/503 等），但 body 统一为此结构。

错误码枚举：
- `NOT_FOUND` — 资源不存在
- `INVALID_INPUT` — 请求数据校验失败
- `STORAGE_ERROR` — 存储不可用（原 503）
- `INTERNAL_ERROR` — 内部错误（原 500）
- `STREAM_ERROR` — WS 流式错误

## 2. WebSocket 实时通道

新增端点 `GET /api/v1/ws`，单 WS 连接替代 SSE 流式 + 提醒轮询。

### 2.1 消息协议

JSON 文本帧。

**客户端 → 服务端：**

```json
{"type": "query", "payload": {"query": "...", "context": {...}, "session_id": "..."}}
{"type": "ping"}
```

**服务端 → 客户端：**

```json
{"type": "stage_start",  "payload": {"stage": "context"}}
{"type": "context_done", "payload": {"context": {...}}}
{"type": "decision",     "payload": {"task_type": "...", "should_remind": true}}
{"type": "done",         "payload": {"status": "delivered", "event_id": "...", "result": {...}}}
{"type": "error",        "payload": {"code": "...", "message": "..."}}
{"type": "reminder",     "payload": {"id": "...", "content": {...}}}
{"type": "pong"}
```

### 2.2 移除端点

- `POST /query/stream` — 删除
- `POST /api/reminders/poll` — 删除
- `GET /api/reminders` 保留（列表查询仍然有用）
- `DELETE /api/reminders/{id}` 保留

### 2.3 连接管理

- 心跳：客户端 30s 发 `ping`，服务端回 `pong`，超 60s 无消息则断开
- 重连：前端指数退避（1s, 2s, 4s, 8s, max 30s）
- query 上下文绑定：首条 message 带 `session_id`，服务端据此关联会话

### 2.4 实现

- `app/api/v1/ws.py` — FastAPI WebSocket 端点
- `app/api/v1/ws_manager.py` — 连接管理器（跟踪连接、用户映射、广播）

## 3. 前端声明式表单

### 3.1 data-ctx-path

HTML input 声明字段路径：

```html
<select id="ctx-emotion" data-ctx-path="driver.emotion">
<input type="number" id="ctx-lat" data-ctx-path="spatial.current_location.latitude">
```

### 3.2 通用函数

```js
function buildContext(rootEl)     // 遍历 [data-ctx-path] → 嵌套 dict
function fillContext(rootEl, ctx) // dict → 回填表单
function resetContext(rootEl)     // 清空全部
```

加字段 = 加 HTML + `data-ctx-path`，JS 不动。

## 4. 前端状态封装

`AppState` 类：

```js
class AppState {
  #currentEventId = null;
  #experimentChart = null;
  #ws = null;

  getCurrentEventId();
  setCurrentEventId(id);
  reset();        // 清空全状态
  destroy();      // 清理 WS、Chart 等资源
}

const state = new AppState(); // 全局唯一实例
```

## 5. 其他前端优化

| 项 | 改法 |
|----|------|
| 实验图自动加载 | `loadExperimentData()` 随 `loadPresets()` 自动执行 |
| 错误通知 UI | 底部 toast 容器，`showToast(message, type)` 统一 |
| CDN Chart.js | 保留 CDN，毕设不需离线 |
| 历史加载错误 | 改用 `showToast` 提示用户 |

## 6. Export 端点增强

`GET /api/v1/export?type=events|settings|all`

新增 `type` query param：
- `events` — 仅记忆事件 JSONL
- `settings` — 仅 TOML 配置
- `all` — 全部（当前行为，默认）

## 7. 反馈扩展

### 7.1 Action 扩展

| Action | 权重影响 | 说明 |
|--------|----------|------|
| `accept` | +0.1（上限 1.0） | 接受，不变 |
| `ignore` | -0.1（下限 0.1） | 忽略，不变 |
| `snooze` | 不变 | 延后 5 分钟，创建 pending reminder |
| `modify` | +0.05 | 修改内容后接受，写 `modified_content` |

### 7.2 前端

执行区反馈按钮：
```
[接受] [忽略] [延后5分钟] [修改]
```

「修改」弹出 `prompt()` 编辑内容，以 `action: "modify"` 提交。

## 8. 后端文件结构变动

```
app/api/
├── __init__.py
├── AGENTS.md          # 更新
├── main.py            # 挂载 v1 router + WS
├── middleware.py       # 新增：X-User-Id 提取
├── errors.py          # 改进：统一错误信封
├── schemas.py         # 更新模型
├── v1/                # 新增：版本化路由
│   ├── __init__.py
│   ├── query.py       # POST /api/v1/query
│   ├── feedback.py    # POST /api/v1/feedback
│   ├── presets.py     # GET/POST/DELETE /api/v1/presets
│   ├── data.py        # GET/DELETE /api/v1/{history,export,data,experiments}
│   ├── sessions.py    # POST /api/v1/sessions/{id}/close
│   ├── reminders.py   # GET/DELETE /api/v1/reminders
│   └── ws.py          # 新增：WS /api/v1/ws
├── stream.py          # 删除（WS 取代）
└── routes/            # 删除（迁移至 v1/）
```

## 9. 测试策略

- 新增 `tests/api/test_v1_*.py` — 新旧并行测试
- WS 端点用 `starlette.testclient.WebSocketTestSession`
- 全部路由测试 mock LLM
- 移除 `tests/agents/test_sse_stream.py`（SSE 删除后无用）
- 更新 `tests/api/test_rest.py` 指向新路径 + X-User-Id header

## 10. 未解决问题

1. WebSocket 连接数限制 — 当前单进程，毕设足够
2. WS 鉴权 — 可在 upgrade 时校验 X-User-Id，但当前无密码体系
3. SSE 移除期间前端需同时支持 WS（新）和 SSE（旧）？不——不向后兼容，一步切换
