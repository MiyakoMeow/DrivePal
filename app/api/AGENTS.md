# API层

`app/api/` —— Strawberry GraphQL, code-first。端点 `/graphql`（内置 GraphiQL）。

**Query:**
```graphql
history(limit, memoryMode, currentUser): [MemoryEventGQL]
scenarioPresets(currentUser): [ScenarioPresetGQL]
experimentResults: ExperimentResults
```

**Mutation（GraphQL Schema 定义，camelCase）：**
```graphql
processQuery(input: {query, memoryMode, context, currentUser, sessionId}): {result, eventId, stages}
submitFeedback(input: {eventId, action, memoryMode, currentUser, modifiedContent}): {status}
saveScenarioPreset(input): ScenarioPresetGQL
deleteScenarioPreset(presetId, currentUser): Boolean
exportData(currentUser): ExportDataResult
deleteAllData(currentUser): Boolean
pollPendingReminders(currentUser, contextInput): PollResult
cancelPendingReminder(reminderId, currentUser): Boolean
getPendingReminders(currentUser): [PendingReminderGQL]
closeSession(sessionId, currentUser): Boolean
```

**命名约定：** Schema 用 camelCase（GraphQL 约定），Python resolver 实现用 snake_case（PEP 8）。Strawberry 自动转换，开发者无需手动映射。例：`processQuery` → `process_query`。

**反馈学习机制：**
1. **权重更新**：`submitFeedback` 接受（accept）时对应类型权重 +0.1（上限 1.0），忽略（ignore）时 -0.1（下限 0.1），新类型初始 0.5。权重存入 `strategies.toml` 的 `reminder_weights`。
2. **权重注入**：权重经 `_format_preference_hint()` 转为自然语言提示，通过 system prompt 的 `{preference_hint}` 占位符和用户 prompt 正文两路注入 JointDecision Agent（权重 ≥ 0.6 强引导，≥ 0.5 弱引导，低于 0.5 不提示）。
3. **注入时机**：JointDecision Agent 调用前，prompt 中注入偏好提示。
4. **交互顺序**：规则引擎先处理硬约束 → JointDecision Agent 语义推理（受偏好影响）→ `postprocess_decision()` 规则后处理（allowed_channels 过滤、非紧急降级等）。

**枚举：** `MemoryModeEnum`, `EmotionEnum`, `WorkloadEnum`, `CongestionLevelEnum`, `ScenarioEnum`

**输入类型（8个）：** `GeoLocationInput`, `DriverStateInput`, `SpatioTemporalContextInput`, `TrafficConditionInput`, `DrivingContextInput`, `ProcessQueryInput`, `FeedbackInput`, `ScenarioPresetInput`

**输出类型（16个）：** `GeoLocationGQL`, `DriverStateGQL`, `TrafficConditionGQL`, `SpatioTemporalContextGQL`, `DrivingContextGQL`, `WorkflowStagesGQL`, `ProcessQueryResult`, `MemoryEventGQL`, `ScenarioPresetGQL`, `FeedbackResult`, `ExportDataResult`, `ExperimentResult`, `ExperimentResults`, `PendingReminderGQL`, `TriggeredReminderGQL`, `PollResult`

**自定义标量：** `JSON`（WorkflowStages 各阶段输出）

**SSE 流式端点：**
- `POST /query/stream` — SSE 流式返回工作流各阶段结果，逐 event 推送（`event: stage_start/context_done/decision/done/error`，其中 stage_start 的 data.stage 含 context/joint_decision/execution），`Content-Type: text/event-stream`

## 错误处理

GraphQL 层异常统一继承 `graphql.error.GraphQLError`，自动转为标准 GraphQL error response：

| 异常类 | 触发条件 |
|--------|----------|
| `InternalServerError` | 未预期的服务器错误 |
| `GraphQLInvalidActionError` | feedback action 非 accept/ignore |
| `GraphQLEventNotFoundError` | 事件 ID 不存在 |

支持外部上下文注入（DrivingContext），跳过LLM推断。

输入转换由 `resolvers/converters.py` 完成：Strawberry Input → `strawberry_to_plain()`（递归 Enum→value, dataclass→dict）→ Pydantic `model_validate()`。

## 服务入口与生命周期

**入口：** `uv run uvicorn app.api.main:app`

**Lifespan 事件：**
- **启动：** `init_storage()` 初始化数据目录（首次运行时迁移旧平铺结构至 `data/users/default/`）；启动 `_periodic_cleanup` 后台任务每 300s 清理过期会话
- **关闭：** `MemoryModule.close()` 关闭 MemoryBank（FAISS 索引落盘 + 后台任务取消等待）；`close_client_cache()` 关闭 Chat 客户端缓存

**中间件：** CORS（当前 `allow_origins=["*"]`，开发用）

**静态文件：** `/static` 挂载 WebUI 目录，`GET /` 返回 `index.html`
