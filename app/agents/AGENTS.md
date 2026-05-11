# Agent 系统

`app/agents/` —— Agent核心模块。

## Agent工作流

四阶段流水线，全异步（async/await）：

```
用户输入 → Context Agent → Task Agent → Strategy Agent → Execution Agent
```

| Agent | 输入 → 输出 | 说明 |
|-------|------------|------|
| Context | 用户+记忆+外部上下文 → JSON上下文 | 有外部数据直接使用，无则LLM推断 |
| Task | 用户+上下文 → JSON任务 | 事件抽取、类型归因 |
| Strategy | 上下文+任务+规则约束+个性化+反馈权重+概率推断 → JSON决策 | 安全约束范围内决策 |
| Execution | 决策 → 结果+event_id | 存储事件，返回提醒 |

`run_with_stages()` 返回各阶段详细输出（可解释性）。

### Agent 提示词

`app/agents/prompts.py`。三个 Agent 各有系统提示词，均为中文 + JSON 输出：

| Agent | 职责 | 输出 |
|-------|------|------|
| Context | 构建统一上下文（时间/位置/交通/偏好/驾驶员状态） | JSON 上下文对象 |
| Task | 事件抽取 + 任务归因（meeting/travel/shopping/contact/other）| JSON 任务对象（含置信度）|
| Strategy | 是否/何时/如何提醒，考虑个性化 + 安全边界 | JSON 决策（should_remind/timing/content/理由），通道由规则引擎约束非 LLM 输出 |

Execution Agent 无单独提示词——执行逻辑由规则引擎硬约束 + 代码实现。

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

### 概率推断

`app/agents/probabilistic.py`。Strategy Agent 前执行，MemoryBank 启用时自动注入 prompt。

1. **意图推断**（`infer_intent`）：MemoryBank 检索 top-20 相似事件 → 按 type 聚合得分 → 归一化得置信度分布 `{intent_confidence, alternative, alt_confidence}`。冷启动（无结果）返回低置信度 0.2，无替代意图。
2. **打断风险评估**（`compute_interrupt_risk`）：`0.4×fatigue + 0.3×workload + 0.2×scenario + 0.1×speed`，结果 ∈ [0,1]。scenario 缺失时 scenario_risk=0.5。
3. **环境开关**：`PROBABILISTIC_INFERENCE_ENABLED=0` 关闭（默认开启）。
