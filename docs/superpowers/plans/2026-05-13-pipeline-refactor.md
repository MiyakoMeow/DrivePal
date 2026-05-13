# 流水线重构 + 实验改进 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 四阶段流水线（Context→Task→Strategy→Execution）→ 三阶段（Context→JointDecision→Execution）。重写 JointDecision prompt（解决信息过载）。修复个性化权重注入。补充实验方法（高难度场景 + 多 Judge）。

**架构：** 删 `_task_node`，改 `_strategy_node` 为 `_joint_decision_node`，prompt 从 dump 整文件变为自然语言提示。JointDecisionOutput 模型 merge Task + Strategy 输出。`_format_preference_hint` / `_format_constraints_hint` 辅助方法生成轻量提示。实验模块新增高难度场景子组 + 多 Judge 交叉验证。

**技术栈：** Python 3.14, Pydantic, pytest (asyncio_mode=auto), ruff, ty

---

## 文件结构

| 文件 | 职责 | 动作 |
|------|------|------|
| `app/agents/prompts.py` | 系统提示词定义 | 删 TASK/STRATEGY prompt，增 JOINT_DECISION prompt |
| `app/agents/workflow.py` | 工作流编排 | 删 _task_node / TaskOutput，增 JointDecisionOutput + 辅助方法 + _joint_decision_node，改 _nodes / run_with_stages / run_stream |
| `app/agents/AGENTS.md` | Agent 系统文档 | 更新四→三阶段描述 |
| `tests/agents/test_llm_json_validation.py` | 输出模型 + 节点测试 | 删 TestTaskOutput，增 TestJointDecisionOutput，改 TestWorkflowValidationPath |
| `experiments/ablation/` | 消融实验 | 补充高难度场景配置 + 多 Judge |

---

### 任务 1：prompts.py — 替换 Task/Strategy → JointDecision

**文件：** 修改 `app/agents/prompts.py`

- [ ] **步骤 1：替换 prompt 定义**

删 `TASK_SYSTEM_PROMPT`（行 27-43）和 `STRATEGY_SYSTEM_PROMPT`（行 45-70），新增 `JOINT_DECISION_SYSTEM_PROMPT`。更新 `SYSTEM_PROMPTS` dict。

```python
# 删 TASK_SYSTEM_PROMPT, STRATEGY_SYSTEM_PROMPT
# 删旧 SYSTEM_PROMPTS dict

JOINT_DECISION_SYSTEM_PROMPT = """你是车载AI决策Agent，根据用户输入和驾驶上下文，同时完成事件归因和策略决策。

用户请求类型可能是：会议提醒、导航规划、购物清单、联系人或一般咨询。

## 输出格式

输出JSON，包含：

1. task_type: 任务归因（meeting/travel/shopping/contact/other/general）
2. confidence: 置信度（0.0-1.0）
3. entities: 提取的事件列表，每项含 time/location/type/constraints
4. decision: 决策对象
   - should_remind: 是否提醒
   - timing: 时机（now/delay/skip/location）
   - is_emergency: 是否紧急（如急救/事故预警/儿童遗留检测）
   - target_time: 目标时间（timing=delay 或 postpone 时）
   - delay_seconds: 延迟秒数（timing=delay 时）
   - reminder_content: 对象 {speakable_text, display_text, detailed}
   - reason: 决策理由

## 安全约束

{constraints_hint}

## 用户偏好

{preference_hint}

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
    "reason": "用户请求会议提醒"
  }
}"""

# 保留 CONTEXT_SYSTEM_PROMPT 不变（行 3-25）
# 保留 SINGLE_LLM_SYSTEM_PROMPT 不变（架构组消融用）

SYSTEM_PROMPTS = {
    "context": CONTEXT_SYSTEM_PROMPT,
    "joint_decision": JOINT_DECISION_SYSTEM_PROMPT,
}
```

- [ ] **步骤 2：运行 ruff 和 ty 检查**

```bash
uv run ruff check --fix app/agents/prompts.py
uv run ruff format app/agents/prompts.py
uv run ty check app/agents/prompts.py
```

预期：lint/format 无问题，type 检查通过（`JOINT_DECISION_SYSTEM_PROMPT` 未引用 `constraints_hint` / `preference_hint` 占位符——它们是 format 参数，不影响类型检查）。

- [ ] **步骤 3：Commit**

```bash
git add app/agents/prompts.py
git commit -m "refactor: replace Task/Strategy prompts with JointDecision prompt"
```

---

### 任务 2：workflow.py Part 1 — JointDecisionOutput 模型 + 辅助方法

**文件：** 修改 `app/agents/workflow.py`

- [ ] **步骤 1：添加 JointDecisionOutput 模型**

在 `StrategyOutput` 类之后（约行 173）添加：

```python
class JointDecisionOutput(BaseModel):
    """JointDecision Agent JSON 输出模型。

    merge TaskOutput + StrategyOutput，decision 字段以 dict 传递（规则后处理）。
    extra forbid 防止 LLM 注入非法字段。
    """

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

保留 `TaskOutput`（外部模块可能依赖，仅标记 deprecated 注释）。

- [ ] **步骤 2：添加 `_format_constraints_hint` 静态方法**

在 `AgentWorkflow` 中添加（`__init__` 之后）：

```python
@staticmethod
def _format_constraints_hint(driving_context: dict | None) -> str:
    """apply_rules → 自然语言约束提示."""
    if not driving_context:
        return ""
    constraints = apply_rules(driving_context)
    hints: list[str] = []
    channels = constraints.get("allowed_channels")
    if channels:
        ch_str = ", ".join(channels)
        hints.append(f"当前仅建议通过 {ch_str} 通道提醒。")
    max_freq = constraints.get("max_frequency_minutes")
    if max_freq:
        hints.append(f"两次提醒建议至少间隔 {max_freq} 分钟。")
    if constraints.get("only_urgent"):
        hints.append("当前仅紧急提醒适合发送。")
    if constraints.get("postpone"):
        hints.append("当前应延后非紧急提醒。")
    return " ".join(hints)
```

- [ ] **步骤 3：添加 `_format_preference_hint` 方法**

```python
async def _format_preference_hint(self) -> str:
    """从 strategies.toml 读 reminder_weights → 自然语言偏好提示."""
    if get_ablation_disable_feedback():
        return ""
    strategies = await self._strategies_store.read()
    weights = strategies.get("reminder_weights", {})
    if not isinstance(weights, dict):
        return ""
    items: list[tuple[str, float]] = [
        (k, float(v)) for k, v in weights.items() if isinstance(v, (int, float))
    ]
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

- [ ] **步骤 4：运行 lint + type check**

```bash
uv run ruff check --fix app/agents/workflow.py
uv run ruff format app/agents/workflow.py
uv run ty check app/agents/workflow.py
```

- [ ] **步骤 5：Commit**

```bash
git add app/agents/workflow.py
git commit -m "refactor: add JointDecisionOutput model + helper methods"
```

---

### 任务 3：workflow.py Part 2 — 替换 `_strategy_node` 为 `_joint_decision_node`

**文件：** 修改 `app/agents/workflow.py`（行 428-499 附近）

- [ ] **步骤 1：删除 `_strategy_node`（行 428-499）**

删整个方法（`async def _strategy_node` ... 到 `return {"decision": decision}`）。

- [ ] **步骤 2：新增 `_joint_decision_node`**

```python
async def _joint_decision_node(self, state: AgentState) -> dict:
    """JointDecision 节点：合并 Task 归因 + 策略决策为一次 LLM 调用.

    prompt 精简原则：
    - 不注入 strategies.toml 全文，仅读 reminder_weights
    - 规则约束转自然语言（_format_constraints_hint）
    - 概率推断仅传关键信号，非完整 intent dict
    - 权重作为显式引导（_format_preference_hint）
    """
    user_input = state.get("original_query", "")
    context = state.get("context", {})
    driving_context = state.get("driving_context")
    stages = state.get("stages")

    constraints_hint = self._format_constraints_hint(driving_context)
    preference_hint = await self._format_preference_hint()

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
    prompt_body = "\n\n".join(prompt_parts)

    # JointDecision prompt 使用 format() 注入 constraints/preference
    system_prompt = SYSTEM_PROMPTS["joint_decision"].format(
        constraints_hint=constraints_hint or "无特殊约束。",
        preference_hint=preference_hint or "无特殊偏好。",
    )
    full_prompt = f"{system_prompt}\n\n{prompt_body}"
    parsed = await self._call_llm_json(full_prompt)

    try:
        validated = JointDecisionOutput.model_validate(parsed.data or {})
        task = {
            "type": validated.task_type,
            "confidence": validated.confidence,
            "entities": validated.entities,
        }
        decision = validated.decision
    except ValidationError as e:
        logger.warning("JointDecisionOutput validation failed: %s", e)
        raw = parsed.data or {}
        decision = raw.get("decision", {})
        task = {
            "type": raw.get("task_type") or raw.get("type", "general"),
            "confidence": raw.get("confidence", 0.0),
            "entities": raw.get("entities", []),
        }

    # 策略节点逻辑保持：postpone 由 apply_rules 决定
    if driving_context:
        constraints = apply_rules(driving_context)
        decision["postpone"] = constraints.get("postpone", False)

    if stages is not None:
        stages.task = task
        stages.decision = decision

    return {"task": task, "decision": decision}
```

- [ ] **步骤 3：导入对齐**

确认 workflow.py 顶部 import 中 `infer_intent` / `compute_interrupt_risk` / `OVERLOADED_WARNING_THRESHOLD` / `is_enabled` / `apply_rules` 均已导入。确认 `JointDecisionOutput` 在文件内定义。确认 `get_ablation_disable_feedback` 已导入。

- [ ] **步骤 4：运行 lint + type check**

```bash
uv run ruff check --fix app/agents/workflow.py
uv run ruff format app/agents/workflow.py
uv run ty check app/agents/workflow.py
```

- [ ] **步骤 5：Commit**

```bash
git add app/agents/workflow.py
git commit -m "refactor: replace _strategy_node with _joint_decision_node"
```

---

### 任务 4：workflow.py Part 3 — 更新 `_nodes` / `run_with_stages` / `run_stream`

**文件：** 修改 `app/agents/workflow.py`

- [ ] **步骤 1：更新 `self._nodes`**

```python
# 行 278-282 改为
self._nodes = [
    self._context_node,
    self._joint_decision_node,
    self._execution_node,
]
```

- [ ] **步骤 2：更新 `run_with_stages` 的事件循环**

`run_with_stages`（行 705-757）中 `for node_fn in self._nodes` 自动适应三阶段，无需改循环本身。但 state 初始化中的 `"task": None` 仍保留（下游兼容）。注释更新。

关键：`run_with_stages` 的 try 块（行 749）需确认不再引用 `_task_node`。删除行 857 / 869 的 `await self._task_node(...)` 和 `await self._strategy_node(...)`——这些仅存于 `run_stream`。

- [ ] **步骤 3：更新 `run_stream` — Stage 2 改为 JointDecision**

`run_stream`（行 791-903）中：

**删除** Task stage 块（约行 854-864）：
```python
# 删除以下整段
# Stage 2: Task
yield {"event": "stage_start", "data": {"stage": "task"}}
try:
    updates = await self._task_node(state)
    ...
```

**修改** 原 Strategy stage 块（约行 866-884）为：

```python
# Stage 2: JointDecision
yield {"event": "stage_start", "data": {"stage": "joint_decision"}}
try:
    updates = await self._joint_decision_node(state)
    state.update(updates)
    decision = state.get("decision") or {}
    task_type = (state.get("task") or {}).get("type", "general")
    yield {
        "event": "decision",
        "data": {
            "should_remind": decision.get("should_remind"),
            "task_type": task_type,
        },
    }
except Exception as e:
    logger.warning(
        "run_stream %s stage failed: %s", "joint_decision", e, exc_info=True
    )
    yield {
        "event": "error",
        "data": {"code": "JOINT_DECISION_FAILED", "message": str(e)},
    }
    self._log_conversation_turn(state, session_id, user_input)
    return
```

**修改** Stage 3 注释（原 "Stage 4: Execution" → "Stage 3: Execution"），yield 事件不变。

- [ ] **步骤 4：检查 import 区**

确认 `AgentState`、`WorkflowStages` 等依赖均存在。检查 `_task_node` 不再被任何位置引用（删完后 grep 确认）。

运行：
```bash
grep -n "_task_node" app/agents/workflow.py
# 预期：无输出（已被彻底删除）
grep -n "_strategy_node" app/agents/workflow.py  
# 预期：无输出
```

- [ ] **步骤 5：运行 lint + type check**

```bash
uv run ruff check --fix app/agents/workflow.py
uv run ruff format app/agents/workflow.py
uv run ty check app/agents/workflow.py
```

- [ ] **步骤 6：运行测试（预期部分失败——下个任务修复）**

```bash
uv run pytest tests/ -v --timeout=60 -x 2>&1 | head -80
```

预期：test_llm_json_validation.py 中 `test_task_node_validation_success` 和 `test_strategy_node_validation_success` 报 `AttributeError`，其他测试应继续通过。

- [ ] **步骤 7：Commit**

```bash
git add app/agents/workflow.py
git commit -m "refactor: update _nodes, run_with_stages, run_stream for 3-stage pipeline"
```

---

### 任务 5：更新测试

**文件：** 修改 `tests/agents/test_llm_json_validation.py`

- [ ] **步骤 1：替换 import**

`workflow` 导入中：删 `StrategyOutput`, `TaskOutput`，增 `JointDecisionOutput`。

```python
from app.agents.workflow import (
    AgentWorkflow,
    ContextOutput,
    JointDecisionOutput,
    LLMJsonResponse,
)
```

保留 `StrategyOutput` 和 `TaskOutput` 的导入也行（不删也行），但新测试用新模型。

- [ ] **步骤 2：替换 TestTaskOutput → TestJointDecisionOutput**

```python
class TestJointDecisionOutput:
    def test_valid_full(self):
        """完整合法输入，字段正确映射。"""
        obj = JointDecisionOutput(
            task_type="meeting",
            confidence=0.9,
            entities=[{"time": "15:00", "location": "3F"}],
            decision={"should_remind": True, "timing": "now"},
        )
        assert obj.task_type == "meeting"
        assert obj.confidence == 0.9
        assert len(obj.entities) == 1
        assert obj.decision["should_remind"] is True

    def test_alias_backward_compat(self):
        """旧 key（type/task_type）均通过 AliasChoices 接受。"""
        data1 = {"task_type": "travel", "decision": {}}
        obj1 = JointDecisionOutput.model_validate(data1)
        assert obj1.task_type == "travel"

        data2 = {"type": "shopping", "decision": {}}
        obj2 = JointDecisionOutput.model_validate(data2)
        assert obj2.task_type == "shopping"

    def test_extra_rejected(self):
        """含额外字段 → ValidationError."""
        data = {"task_type": "meeting", "unknown": True}
        try:
            JointDecisionOutput.model_validate(data)
            pytest.fail("应抛 ValidationError")
        except ValidationError:
            pass
```

- [ ] **步骤 3：更新 TestWorkflowValidationPath**

```python
class TestWorkflowValidationPath:
    @pytest.mark.asyncio
    async def test_context_node_validation_success(self, tmp_path):
        """Context 节点 validate 分支不抛异常。"""
        workflow = AgentWorkflow(data_dir=tmp_path, memory_module=MagicMock())
        workflow._call_llm_json = AsyncMock(
            return_value=LLMJsonResponse(
                raw='{"scenario":"highway","driver_state":{},'
                '"spatial":{},"traffic":{},'
                '"current_datetime":"2026-01-01"}',
            )
        )
        result = await workflow._context_node(
            {
                "original_query": "test",
                "context": {},
                "task": None,
                "decision": None,
                "result": None,
                "event_id": None,
                "driving_context": None,
                "stages": None,
                "session_id": None,
            }
        )
        assert "context" in result

    @pytest.mark.asyncio
    async def test_joint_decision_node_validation_success(self, tmp_path):
        """JointDecision 节点 validate 分支不抛异常。"""
        workflow = AgentWorkflow(data_dir=tmp_path, memory_module=MagicMock())
        workflow._call_llm_json = AsyncMock(
            return_value=LLMJsonResponse(
                raw='{"task_type":"meeting","confidence":0.9,'
                '"entities":[],'
                '"decision":{"should_remind":true,"timing":"now"}}',
            )
        )
        result = await workflow._joint_decision_node(
            {
                "original_query": "test",
                "context": {"scenario": "city_driving"},
                "task": None,
                "decision": None,
                "result": None,
                "event_id": None,
                "driving_context": None,
                "stages": None,
            }
        )
        assert "task" in result
        assert "decision" in result
        assert result["task"]["type"] == "meeting"

    @pytest.mark.asyncio
    async def test_joint_decision_node_fallback_on_bad_json(self, tmp_path):
        """LLM 返回非法 JSON → fallback 分支，不抛异常。"""
        workflow = AgentWorkflow(data_dir=tmp_path, memory_module=MagicMock())
        workflow._call_llm_json = AsyncMock(
            return_value=LLMJsonResponse(raw="not json"),
        )
        result = await workflow._joint_decision_node(
            {
                "original_query": "test",
                "context": {},
                "task": None,
                "decision": None,
                "result": None,
                "event_id": None,
                "driving_context": None,
                "stages": None,
            }
        )
        assert "task" in result
        assert "decision" in result
```

- [ ] **步骤 4：删旧测试方法**

删 `test_task_node_validation_success` 和 `test_strategy_node_validation_success`。

- [ ] **步骤 5：运行测试**

```bash
uv run pytest tests/agents/test_llm_json_validation.py -v
```

预期：全部 PASS。

- [ ] **步骤 6：运行全量测试**

```bash
uv run pytest tests/ -v --timeout=60 2>&1 | tail -30
```

预期：不接入外部 provider 的测试全部通过（排除 `--test-llm` / `--run-integration` 标记测试）。

- [ ] **步骤 7：Commit**

```bash
git add tests/agents/test_llm_json_validation.py
git commit -m "test: update for JointDecision node, remove Task/Strategy node tests"
```

---

### 任务 6：更新 AGENTS.md

**文件：** 修改 `app/agents/AGENTS.md`

- [ ] **步骤 1：更新四阶段描述为三阶段**

```markdown
## Agent工作流

三阶段流水线，全异步（async/await）。入口处先经 ShortcutResolver 匹配快捷指令，命中则跳过 Context/JointDecision 直入 Execution：

```
用户输入 → [ShortcutResolver] ─命中─→ Execution Agent
                              └未命中─→ Context Agent → JointDecision Agent → Execution Agent
```

| Agent | 输入 → 输出 | 说明 |
|-------|------------|------|
| Context | 用户+记忆+外部上下文+对话历史 → JSON上下文 | 有外部数据直接使用，无则LLM推断。`session_id` 非空时注入对话历史 |
| JointDecision | 用户+上下文+规则约束+个性化+概率推断 → JSON任务+决策 | 合并原 Task + Strategy 为一次 LLM 调用，prompt 精简避免信息过载 |
| Execution | 决策 → 结果+event_id | 存储事件，返回提醒。含频次抑制、PendingReminder、隐私脱敏 |

`run_with_stages()` 返回各阶段详细输出（可解释性）。`run_stream()` 以 SSE 逐阶段 yield 事件。
```

- [ ] **步骤 2：删 Task Agent 章节**

搜索章节标题 "| Task | 用户+上下文 → JSON任务 |" 及对应说明，替换为上表内容。JointDecision 字段覆盖 task_type / confidence / entities / decision。

- [ ] **步骤 3：Commit**

```bash
git add app/agents/AGENTS.md
git commit -m "docs: update AGENTS.md for 3-stage pipeline"
```

---

### 任务 7：改进实验配置

**文件：** 修改 `experiments/ablation/architecture_group.py`，`experiments/ablation/safety_group.py`

- [ ] **步骤 1：架构组补充高难度场景**

`architecture_group.py` 中添加 `is_arch_scenario` 的严格版（含高难度）：

```python
def is_hard_arch_scenario(s: Scenario) -> bool:
    """高难度架构测试场景：约束冲突组合。"""
    d = s.synthesis_dims
    if not d:
        return False
    return (
        d["scenario"] == "highway"
        and (
            float(d["fatigue_level"]) > get_fatigue_threshold()
            or d["workload"] == "overloaded"
        )
    )
```

`make_architecture_config` 中新增 `variants_hard` 配置，含 Full + SingleLLM，场景过滤用 `is_hard_arch_scenario`。从 safety 池抽取 25 场景（见 design doc）。

- [ ] **步骤 2：Safety 组多 Judge 配置**

`safety_group.py` 中 `compute_safety_metrics` 末尾增加 judge 一致性分析：

```python
# 多 Judge 交叉验证（仅第二个 Judge 模型配置时启用）
judge_consistency = {}
if has_secondary_judge:
    secondary_scores = await score_with_secondary_judge(scores)
    judge_consistency = compute_judge_consistency(scores, secondary_scores)
    if judge_consistency.get("unstable_ratio", 0) > 0.2:
        logger.warning(
            "Judge 不一致率 %.0f%%",
            judge_consistency["unstable_ratio"] * 100,
        )
metrics["_judge_consistency"] = judge_consistency
```

具体实现：`compute_judge_consistency` 对每 scenario+variant 比较两模型 overall_score，差异 >1 的标记为不稳定。`unstable_ratio` = 不稳定数 / 总数。

- [ ] **步骤 3：运行 lint + type check**

```bash
uv run ruff check --fix experiments/ablation/
uv run ruff format experiments/ablation/
uv run ty check experiments/ablation/
```

- [ ] **步骤 4：Commit**

```bash
git add experiments/ablation/
git commit -m "feat: add hard scenario subset to arch group + multi-judge consistency to safety group"
```

---

---

### 任务 8：个性化组重跑 + 强 Judge 配置（架构验证后执行）

**文件：** 修改 `experiments/ablation/personalization_group.py`，`experiments/ablation/cli.py`

> **注意：** 此任务依赖架构改完 + 重跑消融实验后执行。先完成 1-7，运行全组消融，再处理此任务。

- [ ] **步骤 1：增强权重信号**

确认 `_format_preference_hint`（任务 2）已使用 top-1 权重显式引导逻辑。`personalization_group.py` 中 `run_personalization_group` 在 round 循环中不做 prompt 层面修改（prompt 逻辑在 `workflow.py`），因此无代码改动。只需确认架构改后的权重注入生效——人肉检查 weight_history 中 meeting/travel 等类型权重变化幅度是否合理。

- [ ] **步骤 2：增加阶段轮数**

`personalization_group.py` 中 `STAGES` 改 8→12 轮每阶段：

```python
STAGES: list[tuple[str, int, int]] = [
    ("high-freq", 0, 12),
    ("silent", 12, 24),
    ("visual-detail", 24, 36),
    ("mixed", 36, 48),
]
```

`_build_stages` 中 `available = min(total, 48)`。

`cli.py` 中个性化组场景采样数从 32→48：

```python
if "personalization" in groups_to_run:
    group_scenarios["personalization"] = sample_scenarios(
        all_scenarios,
        48,  # 原 32
        ...
    )
```

- [ ] **步骤 3：配置强 Judge 模型**

`cli.py` 中 `judge = Judge()` 初始化时，确认环境变量 `JUDGE_MODEL` 指向强模型（如 DeepSeek 或 GPT-4 级别）。若未设置，log warning 提示用户配置。

在 `main()` 入口处加检查：

```python
if args.group in ("personalization", "all"):
    judge_model = os.environ.get("JUDGE_MODEL")
    if not judge_model:
        logger.warning(
            "个性化组建议使用强 Judge 模型（设置 JUDGE_MODEL 环境变量），"
            "当前使用默认模型可能导致评分退化。"
        )
```

- [ ] **步骤 4：场景重新采样**

执行 `--synthesize-only` 确保场景库有至少 48 个性化场景（当前 32）。若不足，需合成新场景。

手动指令：
```bash
uv run python -m experiments.ablation --synthesize-only
```

- [ ] **步骤 5：运行个性化组**

```bash
uv run python -m experiments.ablation --group personalization --seed 42
```

预期：weight_history 显示权重变化显著（非全部 0.5），Judge 评分退化率 < 50%。

- [ ] **步骤 6：Commit**

```bash
git add experiments/ablation/personalization_group.py experiments/ablation/cli.py
git commit -m "feat: improve personalization experiment with stronger weights signal + more rounds"
```

---

## 自检清单

- [ ] prompts.py：JOINT_DECISION_SYSTEM_PROMPT 含 `{constraints_hint}` / `{preference_hint}` 占位符——运行时 format 替换
- [ ] workflow.py：`_joint_decision_node` 中 `SYSTEM_PROMPTS["joint_decision"].format(...)` 不会因缺少占位符报错
- [ ] workflow.py：`_task_node` / `_strategy_node` 已从文件中彻底删除（`grep` 确认无残留）
- [ ] workflow.py：`TaskOutput` 保留但不再用于流水线主路径（兼容外部导入）
- [ ] run_stream：yield 事件名 `"joint_decision"` 与前端期望一致（确认无前端依赖 stage 名称）
- [ ] 测试：`test_joint_decision_node_validation_success` + fallback 分支覆盖
- [ ] 实验：`is_arch_scenario` 与 `is_hard_arch_scenario` 互斥（同一场景不进入两个子组）
