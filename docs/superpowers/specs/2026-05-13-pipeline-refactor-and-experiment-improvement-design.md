# 流水线重构与实验改进设计

## 背景

消融实验揭示了三方面问题：

1. **架构组**：四Agent流水线（Full）综合质量 2.9 分，单LLM（SingleLLM）4.88 分，效应量 d=2.58（p<0.001）。反转假设。根因定位为 Strategy Agent prompt 信息过载——注入了 strategies.toml 全文件、规则约束 raw dict、概率推断完整 intent dict 等大量辅助信息，LLM 被干扰。

2. **安全性组**：规则引擎合规率提升 8pp（66% vs 58%），但未达统计显著（d≈0.19）。两个不同 Judge 模型评分差异可达 0.5 分，结论脆弱。

3. **个性化组**：Judge 100% 评 3 分，定量结论不可用。权重学习机制有效（weight_history 显示变化），但决策输出未可靠遵循权重引导——信号强度不足。

## 目标

1. 将四阶段流水线精简为三阶段（Context → JointDecision → Execution）
2. 重写 JointDecision prompt，解决信息过载问题
3. 修复个性化权重信号强度
4. 改进实验方法（高难度场景补充、多 Judge 验证）

---

## 一、架构变更：4 阶段 → 3 阶段

### 变更内容

```
当前四阶段：                   新三阶段：
Context Agent (3.74)          Context Agent (不变)
  → Task Agent (4.26)           → JointDecision Agent [合并 Task + Strategy]
  → Strategy Agent (3.0)           → Execution Agent (不变)
  → Execution Agent
```

### 具体改动

#### 1.1 `app/agents/prompts.py`

- 保留 `CONTEXT_SYSTEM_PROMPT`（内容不变）
- 删除 `TASK_SYSTEM_PROMPT`（可保留为注释供参考）
- 删除 `STRATEGY_SYSTEM_PROMPT`
- 新增 `JOINT_DECISION_SYSTEM_PROMPT`
- 更新 `SYSTEM_PROMPTS` 字典：key `"strategy"` → `"joint_decision"`，删除 `"task"` key
  - 注：`SYSTEM_PROMPTS` 原仅含 `context` / `task` / `strategy` 三个 key，无 `execution` key（Execution Agent 无独立系统提示词，逻辑由代码实现）。删除 task 后字典余 `context` / `joint_decision` 两项。

#### 1.2 `app/agents/workflow.py`

- 删除 `TaskOutput` 数据类（或保留兼容性导入引用）
- 删除 `_task_node` 方法
- 将 `_strategy_node` 改为 `_joint_decision_node`
- `self._nodes` 从 `[context, task, strategy, execution]` 改为 `[context, joint_decision, execution]`
- `run_with_stages`：删掉 Task 阶段的捕获块，保持 3 节点串联
- `run_stream`：删掉 Stage 2（Task）的 yield 事件和 catch 块；Stage 2 → JointDecision yield "joint_decision" 事件
- 新增 `JointDecisionOutput` Pydantic 模型

#### 1.3 `app/agents/AGENTS.md`

- 更新四阶段描述为三阶段
- 删除 Task Agent 小节（或标记为历史兼容）

#### 1.4 实验模块

- 无影响。`ablation_runner.py` 通过 `workflow.run_with_stages()` 调用，下游无需改。
- 但变体枚举中的 Variant 类型无须变更（SINGLE_LLM 仍对比 Full）。

---

## 二、JointDecision prompt 设计（核心）

### 设计原则

1. **干净**：只传最少必要信息，不 dump 整文件
2. **自然语言优先**：规则约束转为一句自然语言描述，非 raw dict
3. **信号显式化**：权重作为主动引导（"请优先处理"），非被动参考
4. **结构化输出**：JSON 含 task_type / confidence / entities / decision

### Prompt 模板

```python
JOINT_DECISION_SYSTEM_PROMPT = """你是车载AI决策Agent，根据用户输入和驾驶上下文，同时完成事件归因和策略决策。

用户请求类型可能是：会议提醒、导航规划、购物清单、联系人或一般咨询。

## 输出格式

输出JSON，包含以下部分：

1. task_type: 任务归因（meeting/travel/shopping/contact/other/general）
2. confidence: 置信度（0.0-1.0）
3. entities: 提取的事件列表（时间/地点/约束等）
4. decision: 决策对象
   - should_remind: 是否提醒
   - timing: 时机（now/delay/skip/location）
   - is_emergency: 是否紧急
   - target_time: 目标时间（timing=delay 或 postpone 时）
   - delay_seconds: 延迟秒数（timing=delay 时）
   - reminder_content: 提醒内容（speakable_text/display_text/detailed）
   - reason: 决策理由

示例：
{
  "task_type": "meeting",
  "confidence": 0.85,
  "entities": [{"time": "15:00", "location": "公司3楼会议室", "type": "meeting"}],
  "decision": {
    "should_remind": true,
    "timing": "now",
    "is_emergency": false,
    "reminder_content": {
      "speakable_text": "3点公司3楼会议",
      "display_text": "会议 · 15:00 · 公司3F",
      "detailed": "会议提醒：下午3点在公司3楼会议室"
    },
    "reason": "用户请求会议提醒，驾驶条件允许即时通知"
  }
}

## 安全约束

{constraints_hint}

## 用户偏好

{preference_hint}"""
```

### 约束提示生成逻辑（`_format_constraints_hint`）

从 `apply_rules(driving_context)` 结果生成自然语言提示：

| 规则输出 | 自然语言提示 |
|---|---|
| `allowed_channels: ["audio"]` | "当前仅建议通过音频通道提醒。" |
| `max_frequency_minutes: 30` | "两次提醒建议至少间隔30分钟。" |
| `only_urgent: true` | "当前仅紧急提醒适合发送。" |
| `postpone: true` | "当前应延后非紧急提醒。" |
| 无约束时 | 空字符串（不输出任何提示） |

多约束时拼接：当前场景：高速驾驶+疲劳度较高。建议仅音频通道提醒，仅紧急提醒适合发送，两次提醒间隔至少30分钟。

### 偏好注入逻辑（`_format_preference_hint`）

- 从 `strategies.toml` 仅读 `reminder_weights` 字段
- 不注入全文件
- 找到 top-1 权重类型：
  - 若 weight > 0.6：输出"用户当前偏好 {type} 类提醒（权重 {w}），若非安全规则冲突请优先处理。"
  - 若 0.5 < weight ≤ 0.6：输出"用户略偏好 {type} 类提醒，可适当考虑。"
  - 若所有权重 ≤ 0.5（含消融模式禁用反馈）：不输出任何提示
- 消融禁用时（`_ablation_disable_feedback.get()`）：所有权重设为 0.5，不输出偏好提示

### 概率推断简化

不再注入完整 `intent` dict（含 top-20 检索得分）。改为：

- 保留 `compute_interrupt_risk` 高风险阈值提示（`"⚠ 当前打断风险较高，请谨慎决定"`）
- 从 `infer_intent` 仅取 `intent_confidence` 和 `type`，生成："用户当前意图倾向：{type}（置信度 {confidence}）。"

---

## 三、代码具体改动

### 3.1 `app/agents/prompts.py`

```python
# 新增
JOINT_DECISION_SYSTEM_PROMPT = """...（见上一节）..."""

# SYSTEM_PROMPTS 更新为
SYSTEM_PROMPTS = {
    "context": CONTEXT_SYSTEM_PROMPT,
    "joint_decision": JOINT_DECISION_SYSTEM_PROMPT,
}

# 删除 TASK_SYSTEM_PROMPT, STRATEGY_SYSTEM_PROMPT
# （可保留为注释以供参考）
```

### 3.2 `app/agents/workflow.py`

#### 新增 JointDecisionOutput 模型

```python
class JointDecisionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    task_type: str = Field(
        default="general",
        validation_alias=AliasChoices("task_type", "type", "task_attribution"),
    )
    confidence: float = Field(
        default=0.0,
        validation_alias=AliasChoices("confidence", "conf"),
    )
    entities: list = Field(
        default_factory=list,
        validation_alias=AliasChoices("entities", "events", "event_list"),
    )
    decision: dict = Field(default_factory=dict)
```

#### `_format_constraints_hint` 辅助方法

作为 `AgentWorkflow` 的内置方法（`@staticmethod`）。

```python
@staticmethod
def _format_constraints_hint(driving_context: dict | None) -> str:
    """apply_rules → 自然语言约束提示。"""
    if not driving_context:
        return ""
    constraints = apply_rules(driving_context)
    hints: list[str] = []
    channels = constraints.get("allowed_channels")
    if channels:
        hints.append(f"当前仅建议通过 {', '.join(channels)} 通道提醒。")
    max_freq = constraints.get("max_frequency_minutes")
    if max_freq:
        hints.append(f"两次提醒建议至少间隔 {max_freq} 分钟。")
    if constraints.get("only_urgent"):
        hints.append("当前仅紧急提醒适合发送。")
    if constraints.get("postpone"):
        hints.append("当前应延后非紧急提醒。")
    return " ".join(hints)
```

#### `_format_preference_hint` 辅助方法

作为 `AgentWorkflow` 的异步方法，从 strategies 读取 `reminder_weights` 生成偏好提示。

```python
async def _format_preference_hint(self) -> str:
    if _ablation_disable_feedback.get():
        return ""
    strategies = await self._strategies_store.read()
    weights = strategies.get("reminder_weights", {})
    if not isinstance(weights, dict) or not weights:
        return ""
    items = [(k, float(v)) for k, v in weights.items() if isinstance(v, (int, float))]
    if not items:
        return ""
    items.sort(key=lambda x: -x[1])
    top_type, top_weight = items[0]
    if top_weight > 0.6:
        return (
            f"用户当前偏好 {top_type} 类提醒（权重 {top_weight}），"
            "若非安全规则冲突请优先处理。"
        )
    if top_weight > 0.5:
        return f"用户略偏好 {top_type} 类提醒，可适当考虑。"
    return ""
```

#### 改写 `_joint_decision_node`

```python
async def _joint_decision_node(self, state: AgentState) -> dict:
    user_input = state.get("original_query", "")
    context = state.get("context", {})
    driving_context = state.get("driving_context")
    stages = state.get("stages")
    
    # 规则约束 → 自然语言
    constraints_hint = self._format_constraints_hint(driving_context)
    
    # 偏好权重 → 自然语言
    preference_hint = await self._format_preference_hint()
    
    # 概率推断（简化）
    prob_hint = ""
    if is_enabled() and self._memory_mode == MemoryMode.MEMORY_BANK:
        try:
            intent = await infer_intent(
                user_input, self.memory_module, user_id=self.current_user,
            )
            risk = compute_interrupt_risk(driving_context or {})
            if intent.get("intent_confidence", 0) > 0.3:
                prob_hint = (
                    f"用户当前意图倾向：{intent.get('type', 'unknown')}"
                    f"（置信度 {intent.get('intent_confidence', 0)}）。"
                )
            if risk >= OVERLOADED_WARNING_THRESHOLD:
                prob_hint += "⚠ 当前打断风险较高，请谨慎决定。"
        except (OSError, RuntimeError, ValueError, TypeError) as e:
            logger.warning("Probabilistic inference failed: %s", e)
    
    # list 拼接避免 Python 隐式字符串拼接的语法陷阱
    prompt_parts: list[str] = [
        f"用户输入：{user_input}",
        f"驾驶上下文：{json.dumps(context, ensure_ascii=False)}",
    ]
    if prob_hint:
        prompt_parts.append(prob_hint)
    if constraints_hint:
        prompt_parts.append(f"安全约束：{constraints_hint}")
    if preference_hint:
        prompt_parts.append(f"用户偏好：{preference_hint}")
    prompt = "\n\n".join(prompt_parts)
    
    full_prompt = f"{SYSTEM_PROMPTS['joint_decision']}\n\n{prompt}"
    parsed = await self._call_llm_json(full_prompt)
    
    try:
        validated = JointDecisionOutput.model_validate(parsed.data or {})
        result = validated.model_dump()
        decision = result.get("decision", {})
        task = {
            "type": result.get("task_type", "general"),
            "confidence": result.get("confidence", 0.0),
            "entities": result.get("entities", []),
        }
    except ValidationError as e:
        logger.warning("JointDecisionOutput validation failed: %s", e)
        raw = parsed.data or {}
        decision = raw.get("decision", {})
        task = {
            "type": raw.get("task_type", raw.get("type", "general")),
            "confidence": raw.get("confidence", 0.0),
            "entities": raw.get("entities", []),
        }
    
    if stages is not None:
        stages.task = task
        stages.decision = decision
    
    return {"task": task, "decision": decision}
```

#### 更新 `self._nodes`

```python
self._nodes = [
    self._context_node,
    self._joint_decision_node,
    self._execution_node,
]
```

### 3.3 `run_with_stages` 和 `run_stream`

`run_with_stages`：三节点串联，去掉 `_task_node` 调用。

`run_stream`：
- 去掉 Stage 2（Task）的 yield `stage_start/task_done`
- Stage 2 改为 JointDecision：yield `stage_start`（stage="joint_decision"）→ yield `decision`（data={should_remind, task_type}）
- Stage 3（原 Exec）改名但逻辑不变

---

## 四、实验方法改进

### 4.1 架构组补充高难度场景

| 子组 | 场景数 | 条件 | 对比 |
|---|---|---|---|
| 低难度 | 50（已有） | 非高速、疲劳≤0.7、非过载 | Full vs SingleLLM |
| 高难度 | 25（新增） | 高速 + 高疲劳/过载 组合 | Full vs SingleLLM |

从 safety 组场景池中选取 25 个综合约束冲突场景（已有合成场景数据），运行 Full vs SingleLLM 对比。

**假设**：高难度下三阶段流水线追平或超越 SingleLLM。

### 4.2 Safety 组多 Judge 验证

使用两个独立 Judge 模型评分：

| Judge | 用途 |
|---|---|
| 主 Judge（DeepSeek 或更强模型） | 主评分，与当前一致 |
| 副 Judge（GLM-4.5-air） | 交叉验证 |

输出：
- 主 + 副各自计算 Cohen's d
- 评分一致性报告：每场景主副评分差异分布
- 若差异 >1 分的场景占比超过 20%，标注为 Judge 不稳定

### 4.3 个性化组重跑

完成架构+ prompt 修复后：
- 增强权重信号（见第二章）
- 使用强 Judge 模型
- 阶段轮数从 8 轮增至 12 轮（总 48 轮）
- 场景数相应从 32 增至 48（重新采样）

---

## 五、未解决问题

1. JointDecision prompt 的初始版本可能需要多轮调整——消融实验数据可验证效果
2. 高难度场景的定义边界：具体哪些维度组合算"高难度"？当前建议（高速 + 高疲劳/过载）可调整
3. 多 Judge 场景下，若两模型结论相矛盾，如何处理？建议以主 Judge 为准，一致性报告为辅
4. 个性化组重跑可能需要更多场景（当前 132 场景库中含 32 个性化场景，增至 48 需重新合成）
