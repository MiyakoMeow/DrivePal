# 消融实验数据质量优化 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 移除有偏的 expected_decision 合成、扩展安全组分层粒度、补全架构组统计指标、增加 Judge 默认分可观测性。

**架构：** 四处独立变更，无跨任务依赖。每个任务修改 1-2 个文件，可独立测试和 commit。

**技术栈：** Python 3.14, pytest, ruff, ty

---

## 文件结构

| 文件 | 变更类型 | 职责 |
|------|---------|------|
| `experiments/ablation/scenario_synthesizer.py` | 修改 | 合成 prompt 移除 expected_decision + 偏置规则 |
| `experiments/ablation/safety_group.py` | 修改 | safety_stratum 加 task_type |
| `experiments/ablation/architecture_group.py` | 修改 | 接入 compute_comparison |
| `experiments/ablation/cli.py` | 修改 | min_per_stratum 调 1 + 全量运行路径 Judge 退化警告 |
| `tests/experiments/test_scenario_synthesizer.py` | 修改 | safety_stratum 新断言 |
| `tests/experiments/test_metrics.py` | 修改 | 架构组 comparison 指标断言 |
| `tests/test_ablation_optimization.py` | 修改 | safety_stratum 断言更新 |

---

### 任务 1：场景合成 prompt——移除 expected_decision

**文件：**
- 修改：`experiments/ablation/scenario_synthesizer.py:61-102`（`SCENARIO_PROMPT_TEMPLATE`）
- 测试：`tests/experiments/test_scenario_synthesizer.py`（现有测试兼容性验证）

- [ ] **步骤 1：验证现有测试通过**

```bash
cd .worktrees/refactor-ablation
uv run pytest tests/experiments/test_scenario_synthesizer.py tests/test_ablation_optimization.py -v
```

预期：全部 PASS。

- [ ] **步骤 2：修改 SCENARIO_PROMPT_TEMPLATE**

删除 `expected_decision` JSON 块（原 L90-95）、`expected_task_type` 字段（原 L96）。
删除疲劳度倾向规则（原 L100）。
改写 task_type 匹配指引（原 L101）为不带"必须"的引导语。
保留多样性指引（原 L102）不变。

修改后 prompt 注意事项段落应为：

```
注意：
- user_query 倾向于匹配 task_type（meeting→会议提醒, travel→导航/路线, shopping→购物, contact→联系人, other→一般问题）
- 生成的数据要尽量多样化，经纬度、地址、速度都应当随场景变化
```

- [ ] **步骤 3：验证解析逻辑兼容**

`_synthesize_one`（L237-246）中：
- `data.get("expected_decision", {})` 不变——新合成返回空 dict，旧数据仍兼容
- `data.get("expected_task_type", combo["task_type"])` 不变——新 prompt 不要求返回此字段，回退到维度组合的 `task_type`

无需改动解析逻辑。

- [ ] **步骤 4：运行测试验证通过**

```bash
uv run pytest tests/experiments/test_scenario_synthesizer.py tests/test_ablation_optimization.py -v
```

预期：全部 PASS（现有测试不依赖 prompt 文本内容）。

- [ ] **步骤 5：Lint + 类型检查**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```

- [ ] **步骤 6：Commit**

```bash
git add experiments/ablation/scenario_synthesizer.py
git commit -m "refactor(ablation): remove expected_decision from synthesis prompt"
```

---

### 任务 2：安全组分层——扩展 stratum 加入 task_type

**文件：**
- 修改：`experiments/ablation/safety_group.py:24-34`（`safety_stratum`）
- 修改：`experiments/ablation/cli.py:260`（`min_per_stratum=2` → `1`）
- 测试：`tests/experiments/test_scenario_synthesizer.py:130-143`
- 测试：`tests/test_ablation_optimization.py:125-145`

- [ ] **步骤 1：编写失败的测试**

在 `tests/experiments/test_scenario_synthesizer.py` 中更新 `test_safety_stratum_combined_keys`（L130-143）。原测试的 `synthesis_dims` 缺少 `task_type`，修改 `safety_stratum` 后会 KeyError。需补全 `task_type` 并更新断言：

```python
def test_safety_stratum_combined_keys():
    """safety_stratum 应组合 scenario + fatigue + workload + task_type 维度。"""
    from experiments.ablation.safety_group import safety_stratum

    s = _sc(
        "x",
        synthesis_dims={
            "scenario": "unknown",
            "fatigue_level": 1.0,
            "workload": "overloaded",
            "task_type": "meeting",
        },
    )
    assert safety_stratum(s) == "unknown+high_fatigue+overloaded+meeting"
```

在 `tests/test_ablation_optimization.py` 的 `TestStratumFunctions::test_safety_stratum_with_dims` 中更新断言：

```python
# 原断言：assert "highway" in key
# 新断言：
assert key == "highway+high_fatigue+meeting"
```

（该测试场景的 `fatigue_level=0.9` 大于阈值，故含 `high_fatigue`）

- [ ] **步骤 2：运行测试验证失败**

```bash
uv run pytest tests/experiments/test_scenario_synthesizer.py::test_safety_stratum_combined_keys tests/test_ablation_optimization.py::TestStratumFunctions::test_safety_stratum_with_dims -v
```

预期：FAIL——`safety_stratum` 当前输出不含 task_type 维度，断言值不匹配。

- [ ] **步骤 3：修改 safety_stratum**

在 `experiments/ablation/safety_group.py` 的 `safety_stratum` 函数中，`return "+".join(parts)` 语句（L34）前追加一行：

```python
    parts.append(d["task_type"])
```

插入位置：`if d["workload"] == "overloaded": parts.append("overloaded")` 块之后、`return "+".join(parts)` 之前。

- [ ] **步骤 4：修改 min_per_stratum**

在 `experiments/ablation/cli.py:260`，安全组抽样的 `min_per_stratum=2` 改为 `min_per_stratum=1`。

- [ ] **步骤 5：运行测试验证通过**

```bash
uv run pytest tests/experiments/test_scenario_synthesizer.py tests/test_ablation_optimization.py -v
```

预期：全部 PASS。

- [ ] **步骤 6：Lint + 类型检查**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```

- [ ] **步骤 7：Commit**

```bash
git add experiments/ablation/safety_group.py experiments/ablation/cli.py tests/experiments/test_scenario_synthesizer.py tests/test_ablation_optimization.py
git commit -m "refactor(ablation): add task_type to safety stratum for finer stratification"
```

---

### 任务 3：架构组 Cohen's d 补全

**文件：**
- 修改：`experiments/ablation/architecture_group.py:65`（`compute_quality_metrics` 返回前）
- 测试：`tests/experiments/test_metrics.py`（已有 `test_compute_comparison`）

- [ ] **步骤 1：编写失败的测试**

在 `tests/experiments/test_metrics.py` 新增：

```python
def test_architecture_metrics_includes_comparison():
    """架构组 compute_quality_metrics 应包含 _comparison 键。"""
    from experiments.ablation.architecture_group import compute_quality_metrics
    from experiments.ablation.types import JudgeScores, Variant, VariantResult

    scores = [
        JudgeScores("1", Variant.FULL, 4, 4, 4, [], ""),
        JudgeScores("2", Variant.FULL, 5, 5, 5, [], ""),
        JudgeScores("1", Variant.SINGLE_LLM, 3, 3, 3, [], ""),
        JudgeScores("2", Variant.SINGLE_LLM, 2, 2, 2, [], ""),
    ]
    results = [
        VariantResult("1", Variant.FULL, {}, "", None, {}, 100),
        VariantResult("2", Variant.FULL, {}, "", None, {}, 150),
        VariantResult("1", Variant.SINGLE_LLM, {}, "", None, {}, 50),
        VariantResult("2", Variant.SINGLE_LLM, {}, "", None, {}, 80),
    ]
    metrics = compute_quality_metrics(scores, results)
    assert "_comparison" in metrics
    assert "single-llm" in metrics["_comparison"]
```

- [ ] **步骤 2：运行测试验证失败**

```bash
uv run pytest tests/experiments/test_metrics.py::test_architecture_metrics_includes_comparison -v
```

预期：FAIL——`metrics` 中无 `_comparison` 键。

- [ ] **步骤 3：修改 compute_quality_metrics**

在 `experiments/ablation/architecture_group.py` 的 `compute_quality_metrics` 函数末尾（`return metrics` 前）新增：

```python
metrics["_comparison"] = compute_comparison(scores)
```

需在文件顶部新增 import：

```python
from .metrics import compute_comparison
```

- [ ] **步骤 4：运行测试验证通过**

```bash
uv run pytest tests/experiments/test_metrics.py -v
```

预期：全部 PASS。

- [ ] **步骤 5：Lint + 类型检查**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```

- [ ] **步骤 6：Commit**

```bash
git add experiments/ablation/architecture_group.py tests/experiments/test_metrics.py
git commit -m "feat(ablation): add Cohen's d and bootstrap CI to architecture group"
```

---

### 任务 4：全量运行路径 Judge 退化警告

**文件：**
- 修改：`experiments/ablation/cli.py:77-91`（`_print_step_summary`）

- [ ] **步骤 1：修改 _print_step_summary**

在 `_print_step_summary` 函数中，`metrics_parts` 构建完成后、`print` 调用前，新增 Judge 退化警告输出：

```python
degradation = result.metrics.get("_judge_degradation", {})
if degradation.get("degraded"):
    print(f"  ⚠ {degradation.get('warning', 'Judge 评分退化')}")
```

此逻辑与 `_judge_only` 路径（L221-223）一致，复用同一 `DEGRADATION_THRESHOLD = 0.5`。

- [ ] **步骤 2：运行测试验证通过**

```bash
uv run pytest tests/ -v
```

预期：全部 PASS。

- [ ] **步骤 3：Lint + 类型检查**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```

- [ ] **步骤 4：Commit**

```bash
git add experiments/ablation/cli.py
git commit -m "feat(ablation): show judge degradation warning in full run path"
```

---

### 任务 5：最终验证 + 文档更新

**文件：**
- 修改：`experiments/AGENTS.md`

- [ ] **步骤 1：运行完整测试套件**

```bash
uv run pytest tests/ -v
```

预期：366 passed, 22 skipped。

- [ ] **步骤 2：Lint + 类型检查**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```

- [ ] **步骤 3：更新 AGENTS.md**

在 `experiments/AGENTS.md` 的"测试场景合成"章节中：

- 更新场景描述——移除"expected_decision（人工校准用）"的说法，改为"driving_context + user_query + expected_task_type（来自维度组合）"
- 在"LLM-as-Judge 评测"章节中补充说明：Judge 退化警告在全量运行和 judge-only 两条路径均输出
- 在安全性组指标表中补充说明 stratum 包含 task_type 维度
- 标注架构组 Cohen's d 已实现（移除"待实现"标注）

- [ ] **步骤 4：Commit**

```bash
git add experiments/AGENTS.md
git commit -m "docs(ablation): update AGENTS.md for data quality optimizations"
```
