# API层

`app/api/` —— Strawberry GraphQL, code-first。端点 `/graphql`（内置 Playground）。

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

反馈学习：submitFeedback 接受时对应类型权重 +0.1（上限 1.0），忽略时 -0.1（下限 0.1），不存在类型初始 0.5。权重存入 `strategies.toml` 的 `reminder_weights`，Strategy Agent prompt 中注入偏好高权重类型。

**枚举：** `MemoryModeEnum`, `EmotionEnum`, `WorkloadEnum`, `CongestionLevelEnum`, `ScenarioEnum`

**输入类型（9个）：** `GeoLocationInput`, `DriverStateInput`, `SpatioTemporalContextInput`, `TrafficConditionInput`, `DrivingContextInput`, `ProcessQueryInput`, `FeedbackInput`, `ScenarioPresetInput`, `DeleteDataInput`

**输出类型（11个）：** `GeoLocationGQL`, `DriverStateGQL`, `TrafficConditionGQL`, `SpatioTemporalContextGQL`, `DrivingContextGQL`, `WorkflowStagesGQL`, `ProcessQueryResult`, `MemoryEventGQL`, `ScenarioPresetGQL`, `FeedbackResult`, `ExportDataResult`

**自定义标量：** `JSON`（WorkflowStages 各阶段输出）

**错误类：**
- `InternalServerError` — 内部服务器错误
- `GraphQLInvalidActionError` — 无效操作类型
- `GraphQLEventNotFoundError` — 事件不存在

支持外部上下文注入（DrivingContext），跳过LLM推断。

输入转换由 `converters.py` 完成：Strawberry Input → `strawberry_to_plain()`（递归 Enum→value, dataclass→dict）→ Pydantic `model_validate()`。

## 服务入口与生命周期

**入口：** `uv run uvicorn app.api.main:app`

**Lifespan 事件：**
- **启动：** `init_storage()` 初始化数据目录（首次运行时迁移旧平铺结构至 `data/users/default/`）
- **关闭：** `MemoryModule.close()` 关闭 MemoryBank（FAISS 索引落盘 + 后台任务取消等待）

**中间件：** CORS（当前 `allow_origins=["*"]`，开发用）

**静态文件：** `/static` 挂载 WebUI 目录，`GET /` 返回 `index.html`
