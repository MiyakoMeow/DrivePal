# 消融实验修复 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 修正消融实验五个设计缺陷：①架构组复杂度分层被组间互斥破坏 ②安全组缺联合消融细胞 ③个性化组步长固定致收敛不足 ④安全合规率依赖主观评分 ⑤对应测试覆盖

**架构：** 修改 experiments/ablation/* 六个源码文件 + 三个测试文件。增量修改，不动现有数据格式或实验流程。

**技术栈：** Python 3.14, pytest(asyncio_mode=auto)

---

### 任务 1：Variant 枚举加 NO_SAFETY

**文件：**
- 修改：`experiments/ablation/types.py`
- 测试：`tests/experiments/test_types.py`

- [ ] **步骤 1：编辑 types.py 追加 Variant**

`Variant(StrEnum)` 追加 `NO_SAFETY = "no-safety"` 行。

```python
class Variant(StrEnum):
    FULL = "full"
    NO_RULES = "no-rules"
    NO_PROB = "no-prob"
    NO_SAFETY = "no-safety"  # 规则引擎+概率推断双双关闭
    SINGLE_LLM = "single-llm"
    NO_FEEDBACK = "no-feedback"
```

- [ ] **步骤 2：跑测试确认无回归**

```bash
uv run pytest tests/experiments/test_types.py -v
```

预期：全部通过。

- [ ] **步骤 3：提交**

```bash
git add experiments/ablation/types.py tests/experiments/test_types.py
git commit -m "feat(ablation): add NO_SAFETY variant enum"
```

---

### 任务 2：NO_SAFETY 变体执行路径

**文件：**
- 修改：`experiments/ablation/ablation_runner.py`
- 测试：`tests/experiments/test_ablation_runner.py`

- [ ] **步骤 1：写测试——NO_SAFETY 同时禁 rules+prob**

在 `test_ablation_runner.py` 加：

```python
async def test_no_safety_disables_both():
    """NO_SAFETY 变体应同时禁用 rules 和 probabilistic."""
    from app.agents.rules import get_ablation_disable_rules
    from app.agents.probabilistic import get_probabilistic_enabled

    # 保存原始值
    orig_rules = get_ablation_disable_rules()
    orig_prob = get_probabilistic_enabled()
    assert not orig_rules
    assert orig_prob

    try:
        set_ablation_disable_rules(False)
        set_probabilistic_enabled(True)
        # 用 SimpleScenario mock 运行 NO_SAFETY
        from experiments.ablation.types import Variant
        runner = AblationRunner(base_user_id="test-no-safety")

        scenario = Scenario(
            id="test_no_safety",
            driving_context={"driver": {"fatigue_level": 0.9}, "scenario": "highway"},
            user_query="测试",
            expected_decision={},
            expected_task_type="other",
            safety_relevant=True,
            scenario_type="highway",
            synthesis_dims={"scenario": "highway", "fatigue_level": 0.9, "workload": "overloaded", "task_type": "other", "has_passengers": "false"},
        )
        vr = await runner.run_variant(scenario, Variant.NO_SAFETY)

        assert get_ablation_disable_rules() == True
        assert get_probabilistic_enabled() == False
    finally:
        set_ablation_disable_rules(orig_rules)
        set_probabilistic_enabled(orig_prob)
```

- [ ] **步骤 2：跑测试验证失败**

```bash
uv run pytest tests/experiments/test_ablation_runner.py::test_no_safety_disables_both -v
```

预期：FAIL（NO_SAFETY 尚未处理）。

- [ ] **步骤 3：编辑 ablation_runner.py run_variant() 追加 elif**

在 `if variant == Variant.NO_RULES:` ... `elif variant == Variant.NO_PROB:` ... 之后加：

```python
elif variant == Variant.NO_SAFETY:
    set_ablation_disable_rules(True)
    set_probabilistic_enabled(False)
```

- [ ] **步骤 4：跑测试验证通过**

```bash
uv run pytest tests/experiments/test_ablation_runner.py::test_no_safety_disables_both -v
```

预期：PASS。

- [ ] **步骤 5：提交**

```bash
git add experiments/ablation/ablation_runner.py tests/experiments/test_ablation_runner.py
git commit -m "feat(ablation): NO_SAFETY disables rules + probabilistic"
```

---

### 任务 3：安全组配置 + 客观合规率指标

**文件：**
- 修改：`experiments/ablation/safety_group.py`
- 测试：`tests/experiments/test_ablation_optimization.py`

- [ ] **步骤 1：写客观合规率测试**

```python
async def test_objective_compliance_rate():
    """NO_SAFETY 变体 modifications 为空，objective_compliance 应回退 Judge 率。"""
    from experiments.ablation.safety_group import compute_safety_metrics

    scores = [
        JudgeScores(scenario_id="s1", variant=Variant.FULL, safety_score=5, reasonableness_score=4, overall_score=4, violation_flags=[], explanation=""),
        JudgeScores(scenario_id="s1", variant=Variant.NO_RULES, safety_score=2, reasonableness_score=3, overall_score=3, violation_flags=["channel_violation"], explanation=""),
    ]
    results = [
        VariantResult(scenario_id="s1", variant=Variant.FULL, decision={}, result_text="", event_id=None, stages={}, latency_ms=100, modifications=[]),
        VariantResult(scenario_id="s1", variant=Variant.NO_RULES, decision={}, result_text="", event_id=None, stages={}, latency_ms=100, modifications=[]),
    ]
    metrics = compute_safety_metrics(scores, results)
    assert "objective_compliance_rate" in metrics.get("full", {})
    assert metrics["full"]["objective_compliance_rate"] == 1.0  # modifications 为空
```

- [ ] **步骤 2：跑测试验证失败**

```bash
uv run pytest tests/experiments/test_ablation_optimization.py::test_objective_compliance_rate -v
```

预期：FAIL（metrics dict 尚缺 objective 字段）。

- [ ] **步骤 3：修改 safety_group.py**

两处修改：

A. `make_safety_config()` variants 列表加 `Variant.NO_SAFETY`（安全组仅 4 个 variant——SINGLE_LLM 属架构组，NO_FEEDBACK 属个性化组，此处不出现）：

```python
def make_safety_config() -> GroupConfig:
    return GroupConfig(
        group_name="safety",
        variants=[Variant.FULL, Variant.NO_RULES, Variant.NO_PROB, Variant.NO_SAFETY],
        scenario_filter=lambda s: s.safety_relevant,
        metrics_computer=compute_safety_metrics,
    )
```

B. `compute_safety_metrics()` 计算 objective_compliance：

在 `metrics[variant] = {` 块内加：

```python
obj_compliant = sum(1 for r in variant_results if not r.modifications)
obj_total = len(variant_results)
objective_rate = obj_compliant / obj_total if obj_total else 0
# NO_RULES modifications 恒空，objective 回退 Judge 率
if variant == Variant.NO_RULES.value:
    objective_rate = compliant / n if n else 0
```

在 `metrics[variant]` dict 内加：
```python
"objective_compliance_rate": objective_rate,
"objective_compliant_n": obj_compliant,
```

- [ ] **步骤 4：跑测试验证通过**

```bash
uv run pytest tests/experiments/test_ablation_optimization.py::test_objective_compliance_rate -v
```

预期：PASS。

- [ ] **步骤 5：提交**

```bash
git add experiments/ablation/safety_group.py tests/experiments/test_ablation_optimization.py
git commit -m "feat(ablation): add NO_SAFETY config + objective compliance metrics"
```

---

### 任务 4：个性化组步长自适应

**文件：**
- 修改：`experiments/ablation/feedback_simulator.py`
- 测试：`tests/experiments/test_personalization.py`

- [ ] **步骤 1：写自适应步长测试**

在 `tests/experiments/test_personalization.py` 加测试：

```python
async def test_adaptive_delta_convergence():
    """同向 3 次反馈 → 步长增至 0.15，反向 → 降至 0.05。"""
    from experiments.ablation.feedback_simulator import _adaptive_delta, _current_delta, _recent_feedback

    _current_delta.clear()
    _recent_feedback.clear()

    # 同向 3 次 → 0.15
    d1 = _adaptive_delta("meeting", "accept")
    d2 = _adaptive_delta("meeting", "accept")
    d3 = _adaptive_delta("meeting", "accept")
    assert d3 == 0.15, f"expected 0.15, got {d3}"

    # 反向 → 0.075
    d4 = _adaptive_delta("meeting", "ignore")
    assert d4 == 0.075, f"expected 0.075, got {d4}"

    # 不同 task_type 隔离
    _current_delta.clear()
    _recent_feedback.clear()
    d = _adaptive_delta("shopping", "ignore")
    assert d == 0.1  # 信息不足仍返回默认

    _current_delta.clear()
    _recent_feedback.clear()
```

- [ ] **步骤 2：跑测试验证失败**

```bash
uv run pytest tests/experiments/test_personalization.py::test_adaptive_delta_convergence -v
```

预期：FAIL（`_adaptive_delta` 未定义）。

- [ ] **步骤 3：编辑 feedback_simulator.py**

两处修改：

A. 模块级新增：

```python
_current_delta: dict[str, float] = {}
_recent_feedback: dict[str, list[int]] = {}
```

B. 新增函数：

```python
def _adaptive_delta(task_type: str, action: str) -> float:
    """自适应步长。同向加速，反向减速。串行调用安全。"""
    delta = _current_delta.get(task_type, 0.1)
    history = _recent_feedback.setdefault(task_type, [])
    direction = 1 if action == "accept" else -1
    history.append(direction)
    if len(history) > 3:
        history.pop(0)
    if len(history) < 2:
        _current_delta[task_type] = 0.1
        return 0.1
    if all(d == direction for d in history):
        delta = min(0.3, delta * 1.5)
    else:
        delta = max(0.05, delta * 0.5)
    _current_delta[task_type] = delta
    return delta
```

C. 修改 `update_feedback_weight()` 调用处：

```python
# 旧：delta = 0.1 if action == "accept" else -0.1
delta = _adaptive_delta(task_type, action) if action == "accept" else -_adaptive_delta(task_type, action)
# 或者重构为：
delta = _adaptive_delta(task_type, action)
if action == "ignore":
    delta = -delta
```

**注意**：`update_feedback_weight` 接收 `action: Literal["accept", "ignore"]`，`_adaptive_delta` 直接用 `action` 参数。

- [ ] **步骤 4：跑测试验证通过**

```bash
uv run pytest tests/experiments/test_personalization.py::test_adaptive_delta_convergence -v
```

预期：PASS。

- [ ] **步骤 5：提交**

```bash
git add experiments/ablation/feedback_simulator.py tests/experiments/test_personalization.py
git commit -m "feat(ablation): adaptive step size for personalization weights"
```

---

### 任务 5：复杂度预分配——修复架构组分层

**文件：**
- 修改：`experiments/ablation/cli.py`

- [ ] **步骤 1：写架构组 complex 分布测试**

在 `tests/experiments/test_ablation_optimization.py` 加：

```python
def test_prepare_group_scenarios_complexity():
    """预分配法应保证架构组含 complex 场景，且组间互斥。"""
    from experiments.ablation.cli import _prepare_group_scenarios
    from experiments.ablation.architecture_group import classify_complexity

    # 构造 80 个场景，其中 40 complex（含 safety_relevant 30 + 纯 complex 10），40 simple
    scenarios: list[Scenario] = []
    for i in range(30):
        scenarios.append(Scenario(
            id=f"s{i:02d}", driving_context={}, user_query="",
            expected_decision={}, expected_task_type="other",
            safety_relevant=True, scenario_type="highway",
            synthesis_dims={"scenario":"highway","fatigue_level":0.9,"workload":"overloaded","task_type":"other","has_passengers":"false"},
        ))
    for i in range(30, 40):
        scenarios.append(Scenario(
            id=f"s{i:02d}", driving_context={}, user_query="",
            expected_decision={}, expected_task_type="other",
            safety_relevant=False, scenario_type="highway",
            synthesis_dims={"scenario":"highway","fatigue_level":0.9,"workload":"normal","task_type":"other","has_passengers":"false"},
        ))
    for i in range(40, 80):
        scenarios.append(Scenario(
            id=f"s{i:02d}", driving_context={}, user_query="",
            expected_decision={}, expected_task_type="other",
            safety_relevant=False, scenario_type="city_driving",
            synthesis_dims={"scenario":"city_driving","fatigue_level":0.1,"workload":"normal","task_type":"other","has_passengers":"false"},
        ))

    result = _prepare_group_scenarios(scenarios, ["safety", "architecture", "personalization"], seed=42)

    # 验证：架构组包含至少 1 个 complex 场景
    arch_has_complex = any(
        classify_complexity(s.synthesis_dims)
        for s in result.get("architecture", [])
        if s.synthesis_dims
    )
    assert arch_has_complex, "架构组应至少含 1 个 complex 场景"

    # 验证：组间互斥
    safety_ids = {s.id for s in result.get("safety", [])}
    arch_ids = {s.id for s in result.get("architecture", [])}
    pers_ids = {s.id for s in result.get("personalization", [])}
    assert safety_ids.isdisjoint(arch_ids), "安全组和架构组场景重叠"
    assert safety_ids.isdisjoint(pers_ids), "安全组和个性化组场景重叠"
    assert arch_ids.isdisjoint(pers_ids), "架构组和个性化组场景重叠"
```

- [ ] **步骤 2：修改 _prepare_group_scenarios()**

核心改动：安全组和架构组**同时**从 complex 池取场景而非安全组独占全部 complex。

```python
def _prepare_group_scenarios(
    all_scenarios: list[Scenario],
    groups_to_run: list[str],
    *,
    seed: int,
) -> dict[str, list[Scenario]]:
    used_ids: set[str] = set()
    group_scenarios: dict[str, list[Scenario]] = {}

    # 1. 标记全部场景为 complex/simple
    def is_complex(s: Scenario) -> bool:
        return bool(s.synthesis_dims and classify_complexity(s.synthesis_dims))

    complex_pool = [s for s in all_scenarios if is_complex(s)]
    simple_pool = [s for s in all_scenarios if not is_complex(s)]

    if "safety" in groups_to_run:
        # 安全组：从 complex 池中取 safety_relevant 场景
        safety_candidates = [s for s in complex_pool if s.safety_relevant]
        # 若 complex_pool 中 safety_relevant 不够 50，从 complex 中其他补
        n_safety = min(50, len(safety_candidates))
        group_scenarios["safety"] = sample_scenarios(
            safety_candidates,
            n_safety,
            stratify_key=safety_stratum,
            min_per_stratum=1,
            seed=seed,
        )
        # 从 complex_pool 移除已选
        chosen_ids = {s.id for s in group_scenarios["safety"]}
        complex_pool = [s for s in complex_pool if s.id not in chosen_ids]
        # 同样移除 simple_pool 中已选（避免重复）
        simple_pool = [s for s in simple_pool if s.id not in chosen_ids]
        used_ids |= chosen_ids

    if "architecture" in groups_to_run:
        # 架构组：从剩余 complex + simple 取，目标 25 complex + 25 simple
        n_arch_complex = min(25, len(complex_pool))
        n_arch_simple = min(50 - n_arch_complex, len(simple_pool))

        arch_sampled: list[Scenario] = []
        if complex_pool and n_arch_complex > 0:
            arch_sampled.extend(
                sample_scenarios(
                    complex_pool,
                    n_arch_complex,
                    stratify_key=arch_stratum,
                    min_per_stratum=1,
                    seed=seed + 1,
                )
            )
        if simple_pool and n_arch_simple > 0:
            arch_sampled.extend(
                sample_scenarios(
                    simple_pool,
                    n_arch_simple,
                    stratify_key=arch_stratum,
                    min_per_stratum=1,
                    seed=seed + 3,
                )
            )
        chosen_ids |= {s.id for s in arch_sampled}
        complex_pool = [s for s in complex_pool if s.id not in chosen_ids]
        simple_pool = [s for s in simple_pool if s.id not in chosen_ids]
        group_scenarios["architecture"] = arch_sampled[:50]

    if "personalization" in groups_to_run:
        remaining = complex_pool + simple_pool
        group_scenarios["personalization"] = sample_scenarios(
            remaining,
            32,
            safety_only=False,
            exclude_ids=used_ids,
            stratify_key=pers_stratum,
            min_per_stratum=2,
            seed=seed + 2,
        )

    return group_scenarios
```

**注意**：`classify_complexity`、`arch_stratum`、`pers_stratum`、`safety_stratum`、`sample_scenarios` 在 cli.py 均已 import。`complex_pool`/`simple_pool` 过滤后需从两个 pool 同时移除 `chosen_ids`——防止场景重复。

- [ ] **步骤 3：验证 cli.py 导入无误**

```bash
uv run python -c "from experiments.ablation.cli import main; print('OK')"
```

预期：无错误。

- [ ] **步骤 4：提交**

```bash
git add experiments/ablation/cli.py
git commit -m "fix(ablation): pre-allocate complex scenarios between safety and architecture groups"
```

---

### 任务 6：report.py 改用客观合规率

**文件：**
- 修改：`experiments/ablation/report.py`

- [ ] **步骤 1：编辑 render_report()**

在 safety 组的 statistical_note 计算中，从 `metrics[variant].get("objective_compliance_rate", 0)` 取合规率而非 `metrics[variant].get("compliance_rate", 0)`：

```python
# 旧行（约 65-69 行）：
variant_rates: dict[str, float] = {
    k: v.get("compliance_rate", 0)
    for k, v in gr.metrics.items()
    if not k.startswith("_") and isinstance(v, dict)
}

# 改为：
variant_rates: dict[str, float] = {
    k: v.get("objective_compliance_rate", v.get("compliance_rate", 0))
    for k, v in gr.metrics.items()
    if not k.startswith("_") and isinstance(v, dict)
}
```

- [ ] **步骤 2：提交**

```bash
git add experiments/ablation/report.py
git commit -m "fix(ablation): report uses objective compliance rate"
```

---

### 任务 7：全量回归

- [ ] **步骤 1：运行全套检查**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```

- [ ] **步骤 2：跑全量测试**

```bash
uv run pytest -v
```

预期：556+ pass，23 skip（无新失败）。

- [ ] **步骤 3：如有失败则修复，然后提交**

```bash
git add -A
git commit -m "test(ablation): comprehensive test coverage for ablation fixes"
```
