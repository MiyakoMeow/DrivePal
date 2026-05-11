# app/api - GraphQL API 层

Strawberry GraphQL, code-first。端点 `/graphql`（内置 Playground）。

## 入口（main.py）

- **启动命令**：`uv run uvicorn app.api.main:app`
- **Lifespan 启动**：`init_storage()` 初始化数据目录（首次迁移旧平铺结构至 `data/users/default/`）
- **Lifespan 关闭**：`MemoryModule.close()` 关闭 MemoryBank + `close_client_cache()` 清理会话 + `_periodic_cleanup` 协程
- **中间件**：CORS（当前 `allow_origins=["*"]`，开发用）
- **静态文件**：`/static` 挂载 WebUI 目录，`GET /` 返回 `index.html`
- **Stream 路由**：`/query/stream` SSE 端点，推送 Agent 中间结果

## GraphQL Schema（graphql_schema.py）

**Query:**
```graphql
history(limit, memoryMode, currentUser): [MemoryEvent]
scenarioPresets(currentUser): [ScenarioPreset]
experimentResults: ExperimentResults
```

**Mutation:**
```graphql
processQuery(input: {query, memoryMode, context, currentUser}): {result, eventId, stages}
submitFeedback(input: {eventId, action, modifiedContent, memoryMode, currentUser}): {status}
saveScenarioPreset(input): ScenarioPreset
deleteScenarioPreset(id, currentUser): Boolean
exportData(currentUser): ExportDataResult
deleteAllData(currentUser): Boolean
pollPendingReminders(currentUser, contextInput): PollResult
cancelPendingReminder(reminderId, currentUser): Boolean
getPendingReminders(currentUser): [PendingReminderGQL]
closeSession(sessionId, currentUser): Boolean
```

**枚举：** `MemoryModeEnum`, `EmotionEnum`, `WorkloadEnum`, `CongestionLevelEnum`, `ScenarioEnum`

**输入类型（8个）：** `GeoLocationInput`, `DriverStateInput`, `SpatioTemporalContextInput`, `TrafficConditionInput`, `DrivingContextInput`, `ProcessQueryInput`, `FeedbackInput`, `ScenarioPresetInput`

**输出类型（16个）：** `GeoLocationGQL`, `DriverStateGQL`, `TrafficConditionGQL`, `SpatioTemporalContextGQL`, `DrivingContextGQL`, `WorkflowStagesGQL`, `ProcessQueryResult`, `MemoryEventGQL`, `ScenarioPresetGQL`, `FeedbackResult`, `ExportDataResult`, `ExperimentResult`, `ExperimentResults`, `PendingReminderGQL`, `TriggeredReminderGQL`, `PollResult`

**自定义标量：** `JSON`（WorkflowStages 各阶段输出）

**错误类：**
- `InternalServerError` — 内部服务器错误
- `GraphQLInvalidActionError` — 无效操作类型
- `GraphQLEventNotFoundError` — 事件 ID 不存在

## Resolvers

| 文件 | 职责 |
|------|------|
| `query.py` | Query resolvers（history, scenarioPresets, experimentResults） |
| `mutation.py` | Mutation resolvers（processQuery, submitFeedback, saveScenarioPreset 含定时/位置触发提醒等） |
| `errors.py` | GraphQL 错误类定义 |
| `converters.py` | 输入转换：Strawberry Input → `strawberry_to_plain()` → Pydantic `model_validate()`；另含 `input_to_context`、`dict_to_gql_context`、`preset_store` 等工具函数 |

## 反馈学习

submitFeedback 接受时对应事件类型权重 +0.1（上限 1.0），忽略时 -0.1（下限 0.1），不存在类型初始 0.5。权重存入 `strategies.toml` 的 `reminder_weights`，Strategy Agent prompt 中注入偏好高权重类型。
