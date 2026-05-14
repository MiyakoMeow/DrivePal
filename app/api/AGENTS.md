# API 层

`app/api/` — FastAPI REST。主路由 `/api` 前缀；流式端点 `/query/stream`。

## 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/api/query` | 处理查询，返完整工作流结果 |
| POST | `/query/stream` | SSE流式返各阶段结果 |
| POST | `/api/feedback` | 提交反馈(accept/ignore) |
| GET | `/api/history` | 查询历史记忆事件 |
| GET | `/api/export` | 导出当前用户全量文本数据 |
| DELETE | `/api/data` | 删除当前用户全量数据 |
| GET | `/api/experiments` | 查询实验结果对比 |
| GET | `/api/presets` | 查询场景预设 |
| POST | `/api/presets` | 保存场景预设 |
| DELETE | `/api/presets/{id}` | 删除预设 |
| POST | `/api/reminders/poll` | 轮询待触发提醒 |
| DELETE | `/api/reminders/{id}` | 取消提醒 |
| GET | `/api/reminders` | 获取待触发提醒列表 |
| POST | `/api/sessions/{id}/close` | 关闭会话 |

Schema定义于 `app/api/schemas.py` + `app/schemas/query.py`。

## SSE流式

`POST /query/stream`，`Content-Type: text/event-stream`。逐阶段推送 stage_start/context_done/decision/done/error。快捷指令命中时跳中间事件。

## 错误处理

`app/api/errors.py`。`safe_memory_call` 包装记忆调用，异常转 HTTPException：

| 异常 | 状态码 |
|------|--------|
| OSError | 503 |
| ValueError | 422 |
| 其余 | 500 |

`query.py` 额外捕获 `ChatModelUnavailableError` → 503。

## 服务入口

**启动**：`uv run uvicorn app.api.main:app`

**Lifespan**：
- 启动：`init_storage()` 初始化数据目录；`_periodic_cleanup` 后台每300s清理过期会话
- 关闭：`MemoryModule.close()` FAISS落盘；`close_client_cache()` 关闭Chat缓存

**中间件**：CORS `allow_origins=["*"]`（开发用）

**路由注册**：`app/api/routes/__init__.py`，6子模块汇总为 `api_router`。

**静态文件**：`/static` → WebUI，`GET /` → index.html

## 反馈学习

`POST /api/feedback` 将更新写入 `strategies.toml` 的 `reminder_weights`。accept +0.1（上限1.0），ignore -0.1（下限0.1），基值0.5。

权重注入流程（`app/agents/` 层实现，API层仅暴露写入）：
1. `_format_preference_hint()` 将权重转自然语言提示
2. 经 system prompt `{preference_hint}` + 用户prompt两路注入 JointDecision
3. 权重 ≥0.6 强引导，≥0.5 弱引导，<0.5 不提示
4. 规则引擎硬约束 → LLM语义推理 → `postprocess_decision()` 后处理
