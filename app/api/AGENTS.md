# app/api - GraphQL API 层

Strawberry GraphQL, code-first。端点 `/graphql`（内置 Playground）。

## 入口（main.py）

- **启动命令**：`uv run uvicorn app.api.main:app`
- **Lifespan 启动**：`init_storage()` 初始化数据目录（首次迁移旧平铺结构至 `data/users/default/`）
- **Lifespan 关闭**：`MemoryModule.close()` 关闭 MemoryBank（FAISS 索引落盘 + 后台任务取消等待）
- **中间件**：CORS（当前 `allow_origins=["*"]`，开发用）
- **静态文件**：`/static` 挂载 WebUI 目录，`GET /` 返回 `index.html`

## GraphQL Schema（graphql_schema.py）

**Query:**
```graphql
history(limit, memoryMode): [MemoryEvent]
scenarioPresets: [ScenarioPreset]
```

**Mutation:**
```graphql
processQuery(input: {query, memoryMode, context, currentUser}): {result, eventId, stages}
submitFeedback(input: {eventId, action, memoryMode, currentUser}): {status}
saveScenarioPreset(input): ScenarioPreset
deleteScenarioPreset(id): Boolean
exportData(currentUser): ExportDataResult
deleteAllData(currentUser): Boolean
```

**枚举：** `MemoryModeEnum`, `EmotionEnum`, `WorkloadEnum`, `CongestionLevelEnum`, `ScenarioEnum`

**输入类型（9个）：** `GeoLocationInput`, `DriverStateInput`, `SpatioTemporalContextInput`, `TrafficConditionInput`, `DrivingContextInput`, `ProcessQueryInput`, `FeedbackInput`, `ScenarioPresetInput`, `DeleteDataInput`

**输出类型（11个）：** `GeoLocationGQL`, `DriverStateGQL`, `TrafficConditionGQL`, `SpatioTemporalContextGQL`, `DrivingContextGQL`, `WorkflowStagesGQL`, `ProcessQueryResult`, `MemoryEventGQL`, `ScenarioPresetGQL`, `FeedbackResult`, `ExportDataResult`

**自定义标量：** `JSON`（WorkflowStages 各阶段输出）

**错误类：**
- `InternalServerError` — 内部服务器错误
- `GraphQLInvalidActionError` — 无效操作类型
- `GraphQLEventNotFoundError` — 事件不存在

## Resolvers

| 文件 | 职责 |
|------|------|
| `query.py` | Query resolvers（history, scenarioPresets） |
| `mutation.py` | Mutation resolvers（processQuery, submitFeedback 等） |
| `errors.py` | GraphQL 错误类定义 |
| `converters.py` | 输入转换：Strawberry Input → `strawberry_to_plain()` → Pydantic `model_validate()` |

## 反馈学习

submitFeedback 接受时对应事件类型权重 +0.1（上限 1.0），忽略时 -0.1（下限 0.1），不存在类型初始 0.5。权重存入 `strategies.toml` 的 `reminder_weights`，Strategy Agent prompt 中注入偏好高权重类型。
