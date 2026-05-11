# app/agents - Agent 核心模块

四阶段流水线，全异步（async/await）：

```
用户输入 → Context Agent → Task Agent → Strategy Agent → Execution Agent
```

## 文件清单

| 文件 | 职责 |
|------|------|
| `workflow.py` | 流水线编排：`run_with_stages()` + `run_stream()`（SSE 流式） |
| `state.py` | AgentState（TypedDict）+ WorkflowStages（dataclass） |
| `rules.py` | 规则引擎：安全约束加载、合并、`postprocess_decision()` 强制覆盖 |
| `probabilistic.py` | 概率推断：意图置信度、打断风险评估 |
| `prompts.py` | 三个 Agent 的系统提示词模板 |
| `conversation.py` | 多轮对话历史管理 |
| `outputs.py` | OutputRouter 多格式输出（speakable/display/detailed） |
| `pending.py` | PendingReminderManager 延迟/位置触发提醒 |
| `shortcuts.py` | ShortcutResolver 快捷指令（如"取消提醒"） |

## Agent 职责

| Agent | 输入 → 输出 | 说明 |
|-------|------------|------|
| Context | 用户+记忆+外部上下文 → JSON上下文 | 有外部数据直接使用，无则LLM推断 |
| Task | 用户+上下文 → JSON任务 | 事件抽取、类型归因 |
| Strategy | 上下文+任务+规则约束+个性化+反馈权重+概率推断 → JSON决策 | 安全约束范围内决策 |
| Execution | 决策 → 结果+event_id | 存储事件，返回提醒 |

## 提示词（prompts.py）

三个 Agent 各有系统提示词，均为中文 + JSON 输出：

| Agent | 职责 | 输出 |
|-------|------|------|
| Context | 构建统一上下文（时间/位置/交通/偏好/驾驶员状态） | JSON 上下文对象 |
| Task | 事件抽取 + 任务归因（meeting/travel/shopping/contact/other）| JSON 任务对象（含置信度）|
| Strategy | 是否/何时/如何提醒，考虑个性化 + 安全边界 | JSON 决策（should_remind/timing/is_emergency/reminder_content(speakable_text+display_text+detailed)/reason）|

Execution Agent 无单独提示词——执行逻辑由规则引擎硬约束 + 代码实现。

## 规则引擎（rules.py）

7 条规则数据驱动加载自 `config/rules.toml`，失败时回退内置 4 条默认规则。

**调用时机**：`apply_rules()` 在 Strategy Agent prompt 中注入约束，`postprocess_decision()` 在 Execution Agent 输出后强制覆盖。

| 规则 | 条件 | 约束 | 优先级 |
|------|------|------|--------|
| 高速仅音频 | scenario==highway | allowed_channels:[audio], max_frequency:30min | 10 |
| 疲劳抑制 | fatigue_above>0.7(可配) | only_urgent, allowed_channels:[audio] | 20 |
| 过载延后 | workload==overloaded | postpone | 15 |
| 停车全通道 | scenario==parked | allowed_channels:[visual,audio,detailed] | 5 |
| city_driving限制 | scenario==city_driving | allowed_channels:[audio], max_frequency:15min | 8 |
| traffic_jam安抚 | scenario==traffic_jam | allowed_channels:[audio,visual], max_frequency:10min | 7 |
| 乘客在场放宽 | has_passengers && scenario!=highway | extra_channels:[visual] | 3 |

**合并策略**：allowed_channels 取交集（空集回退默认），extra_channels 取并集后追加（去重），max_frequency 取最小值，only_urgent/postpone 取布尔或。

**关键**：`postprocess_decision()` 不可绕过。疲劳阈值环境变量 `FATIGUE_THRESHOLD`（默认0.7）。条件字段支持 AND 组合（scenario / not_scenario / workload / fatigue_above / has_passengers）。

## 概率推断（probabilistic.py）

Strategy Agent 前执行，MemoryBank 启用时自动注入 prompt。环境开关：`PROBABILISTIC_INFERENCE_ENABLED=0` 关闭（默认开启）。

1. **意图推断**（`infer_intent`）：MemoryBank 检索 top-20 相似事件 → 按 type 聚合得分 → 归一化得置信度分布。冷启动返回固定 `intent_confidence=0.2`。
2. **打断风险评估**（`compute_interrupt_risk`）：`0.4×fatigue + 0.3×workload + 0.2×scenario + 0.1×speed`，结果 ∈ [0,1]。scenario 缺失时 scenario_risk=0.5。

## state.py

`AgentState`（TypedDict）贯穿流水线的共享状态；`WorkflowStages`（dataclass）存储各阶段输出快照供可解释性。

## workflow.py

- `run_with_stages()` — 编排四阶段调用流程，返回各阶段输出。
- `run_stream()` — SSE 流式端点。前端实时推送各 Agent 中间结果。

## 未解决问题

突发事件处理：由 Strategy Agent 语义推理 + 规则引擎联合覆盖（无独立模块），论文中说明此设计决策。
