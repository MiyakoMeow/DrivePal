# Agent 系统

`app/agents/` —— Agent核心模块。

## Agent工作流

四阶段流水线，全异步（async/await）。入口处先经 ShortcutResolver 匹配快捷指令，命中则跳过 Context/Task/Strategy 直入 Execution：

```
用户输入 → [ShortcutResolver] ─命中─→ Execution Agent
                              └未命中─→ Context Agent → Task Agent → Strategy Agent → Execution Agent
```

| Agent | 输入 → 输出 | 说明 |
|-------|------------|------|
| Context | 用户+记忆+外部上下文+对话历史 → JSON上下文 | 有外部数据直接使用，无则LLM推断。`session_id` 非空时注入对话历史 |
| Task | 用户+上下文 → JSON任务 | 事件抽取、类型归因 |
| Strategy | 上下文+任务+规则约束+个性化+反馈权重+概率推断 → JSON决策 | 安全约束范围内决策 |
| Execution | 决策 → 结果+event_id | 存储事件，返回提醒。含频次抑制、PendingReminder、隐私脱敏 |

`run_with_stages()` 返回各阶段详细输出（可解释性）。`run_stream()` 以 SSE 逐阶段 yield 事件。

### 快捷指令

`app/agents/shortcuts.py`。`ShortcutResolver` 从 `config/shortcuts.toml` 加载预定义模式，匹配高频场景（如"取消提醒""提醒我几点到某地"）不走 LLM 流水线，直接构造 decision dict 送入 Execution。

| 类型 | 匹配方式 | 示例 |
|------|---------|------|
| travel | patterns 文本匹配 + 参数解析 | "提醒到家" → location 触发 |
| action | patterns 文本匹配 | "取消提醒" → cancel_last，"延迟" → snooze（可跟时长） |

`resolve(query)` 返回预构建 decision dict 或 None。返回 None 时走正常四阶段。

### 多轮对话

`app/agents/conversation.py`。`ConversationManager` 纯内存，TTL 30 分钟，上限 10 轮。

`_context_node()` 收到 `session_id` 时从 manager 获取历史，以 `conversation_history` 字段注入 prompt，用于解析指代（如"刚才那个"）。记录通过 `_log_conversation_turn()` 自动完成。

### 多格式输出路由

`app/agents/outputs.py`。`OutputRouter.route()` 将 LLM 决策转换为 `MultiFormatContent`：

| 字段 | 说明 | 长度 |
|------|------|------|
| speakable_text | TTS 友好，无标点 | ≤15 字 |
| display_text | HUD 可扫读 | ≤20 字 |
| detailed | 完整文本 | 不限 |
| channel | 目标输出通道（audio/visual/detailed）| |
| interrupt_level | 打断级别（0=不打断/1=紧急缓3s/2=立即打断）| |

`_compute_channel()` 取规则约束 `allowed_channels` 首个，`_compute_interrupt_level()` 按 `is_emergency` / `only_urgent` 判定。

### 待触发提醒

`app/agents/pending.py`。`PendingReminderManager` 管理非即时触发的四种模式：

| timing | 触发类型 | 触发条件 |
|--------|---------|----------|
| delay | time | 当前时间 ≥ target_time（由 delay_seconds 算出） |
| location | location | 当前位置距目标位置 < 500m（停车时 1000m） |
| location_time | location + time | 两者任一满足即触发 |
| postpone | — | 由 `_execution_node()` 直接处理为 location/time/context 兜底 |

`_map_pending_trigger()` 将 decision 映射为 `(trigger_type, trigger_target, trigger_text)`。`location_time` 拆为两条独立 pending 提醒（一条位置触发 + 一条时间触发）。

轮询 `poll(driving_context)` 检查 location（haversine 距离）/ time（>= target_time）/ context（scenario 变化）三种触发条件，满足即标记 triggered。

`cancel_last()` 取消最近一条 pending 提醒，用于"取消提醒"动作。

### 隐私脱敏

Execution 节点写 memory 前调用 `sanitize_context(driving_ctx)` 脱敏位置等敏感字段（`app/memory/privacy.py`）。脱敏后上下文写入 `stages.context` 供日志/调试使用。

### 流式方法

`run_stream()` 使用 `AsyncGenerator[dict]` 逐阶段 yield SSE 事件：

| 事件 | 触发时机 | data 内容 |
|------|---------|----------|
| stage_start | 每个阶段开始前 | `{stage: "context"|"task"|"strategy"|"execution"}` |
| context_done | Context 阶段完成 | `{context: {...}}` |
| task_done | Task 阶段完成 | `{tasks: {...}}` |
| decision | Strategy 阶段完成 | `{should_remind: bool \| None}` |
| done | Execution 阶段完成 | `_build_done_data()` 结果 |
| error | 任一阶段失败 | `{code: string, message: string}` |

快捷指令命中时跳过中间事件，直接 yield done/error。

### 状态管理

`app/agents/state.py`。工作流流水线共享状态定义。

**AgentState**（TypedDict，12 字段）：
| 字段 | 说明 |
|------|------|
| original_query | 原始用户输入 |
| context | Context Agent 输出 |
| task | Task Agent 输出（可为 None） |
| decision | Strategy Agent 输出（可为 None） |
| result | Execution 结果文本（可为 None） |
| event_id | 事件 ID（可为 None） |
| driving_context | 驾驶上下文（可为 None） |
| stages | WorkflowStages 快照（可为 None） |
| output_content | 多格式输出内容（NotRequired） |
| session_id | 会话 ID（NotRequired） |
| pending_reminder_id | 待触发提醒 ID（NotRequired） |
| action_result | 动作执行结果（NotRequired） |

**WorkflowStages**（dataclass，4 字段）：各阶段输出快照（context/task/decision/execution），用于可解释性与调试。

### Agent 提示词

`app/agents/prompts.py`。三个 Agent 各有系统提示词，均为中文 + JSON 输出，含显式字段名和示例：

| Agent | 职责 | 输出 |
|------|------|------|
| Context | 构建统一上下文（scenario/driver_state/spatial/traffic） | JSON 上下文对象（7 字段，含示例） |
| Task | 事件抽取 + 任务归因（type/confidence/entities/description） | JSON 任务对象（4 字段，含示例） |
| Strategy | 是否/何时/如何提醒，考虑个性化 + 安全边界 | JSON 决策（11 字段：should_remind/timing/is_emergency/target_time/delay_seconds/reminder_content/type/reason/allowed_channels/action/postpone），通道由规则引擎约束非 LLM 输出 |

Execution Agent 无单独提示词——执行逻辑由规则引擎硬约束 + 代码实现。

### 输出模型鲁棒性

`app/agents/workflow.py`。`ContextOutput` 和 `TaskOutput` 使用 Pydantic `Field(validation_alias=AliasChoices(...))` 兜底 LLM 字段名漂移——不同模型/温度下可能产出非标准键名。`extra="forbid"` 保持严格校验，但已知变体通过 alias 自动归一化。

| 模型 | 规范键 | 接受的别名 |
|------|--------|-----------|
| TaskOutput | `type` | `task_type`, `task_attribution` |
| TaskOutput | `entities` | `events`, `event_list` |
| TaskOutput | `confidence` | `conf` |
| ContextOutput | `scenario` | `scene`, `driving_scenario` |
| ContextOutput | `driver_state` | `driver`, `state` |
| ContextOutput | `spatial` | `location`, `position` |
| ContextOutput | `traffic` | `traffic_status` |
| ContextOutput | `current_datetime` | `datetime`, `time` |
| ContextOutput | `related_events` | `events`, `history` |

校验失败时回退到原始 LLM 输出继续流程——不作阻塞。

## 规则引擎

`app/agents/rules.py`。Strategy Agent 前执行安全约束，7 条规则数据驱动加载自 `config/rules.toml`。

| 规则 | 条件 | 约束 | 优先级 |
|------|------|------|--------|
| 高速仅音频 | scenario==highway | allowed_channels:[audio], max_frequency:30min | 10 |
| 疲劳抑制 | fatigue_level>0.7（TOML固定值，fallback可配） | only_urgent, allowed_channels:[audio] | 20 |
| 过载延后 | workload==overloaded | postpone | 15 |
| 停车全通道 | scenario==parked | allowed_channels:[visual,audio,detailed] | 5 |
| city_driving限制 | scenario==city_driving | allowed_channels:[audio], max_frequency:15min | 8 |
| traffic_jam安抚 | scenario==traffic_jam | allowed_channels:[audio,visual], max_frequency:10min | 7 |
| 乘客在场放宽 | has_passengers && scenario!=highway | extra_channels:[visual] | 3 |

合并策略：allowed_channels 取交集（空集回退默认），extra_channels 并集后追加（去重），max_frequency 取最小值，only_urgent/postpone 取布尔或。

`load_rules()` 从 `config/rules.toml` 加载，失败时回退内置 4 条默认规则。条件字段支持 scenario / not_scenario / workload / fatigue_above / has_passengers（AND 组合）。

关键：`postprocess_decision()` 在LLM输出后强制覆盖，不可绕过。疲劳阈值环境变量 `FATIGUE_THRESHOLD`（默认0.7）。

### 频次约束运行时执行

`max_frequency_minutes` 由 `apply_rules()` 从规则表中合并得出，但仅在 Execution 节点由 `_check_frequency_guard()` 运行时检查生效——遍历最近记忆事件的时间戳，若距上次提醒不足约束值则返回抑制消息，事件不写入 memory。

### 概率推断

`app/agents/probabilistic.py`。Strategy Agent 前执行，MemoryBank 启用时自动注入 prompt。

1. **意图推断**（`infer_intent`）：MemoryBank 检索 top-20 相似事件 → 按 type 聚合得分 → 归一化得置信度分布 `{intent_confidence, alternative, alt_confidence}`。冷启动（无结果）返回低置信度 0.2，无替代意图。
2. **打断风险评估**（`compute_interrupt_risk`）：`0.4×fatigue + 0.3×workload + 0.2×scenario + 0.1×speed`，结果 ∈ [0,1]。scenario 缺失时 scenario_risk=0.5。
3. **高风险阈值**：`OVERLOADED_WARNING_THRESHOLD = 0.36`，打断风险 ≥ 该值时在 prompt 追加"当前打断风险较高，请谨慎决定"。
4. **环境开关**：`PROBABILISTIC_INFERENCE_ENABLED=0` 关闭（默认开启）。

## 状态输出

Execution 节点的 `_build_done_data()` 返回三种状态：

| 状态 | 条件 | data 字段 |
|------|------|----------|
| pending | 含 pending_reminder_id（延迟/位置触发） | event_id, session_id, status, pending_reminder_id |
| suppressed | result 含"取消"或"抑制"关键字 | event_id, session_id, status, reason |
| delivered | 即时提醒已发送 | event_id, session_id, status, result |

输出内容通过 `OutputRouter.route()` 生成的 `MultiFormatContent` 传递，非原始 decision dict。
