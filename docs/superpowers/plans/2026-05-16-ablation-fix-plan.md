# 消融实验修复 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 修复消融实验三组的方法学问题：架构组 2×2 全因子、死代码清理、安全性统计标注、个性化反馈模型重写。

**架构：** 四独立任务，按依赖序。T1-3 架构组 2×2，T4-5 死代码，T6 报告标注，T7-8 反馈模型。T8 测试延后。

**技术栈：** pytest, async, numpy/scipy, ContextVar

---
## 文件清单

| 文件 | 职责 | 变更 |
|------|------|------|
| `experiments/ablation/architecture_group.py` | 架构组实验 | 加 `classify_complexity`，重写 `compute_quality_metrics`，删 `is_arch_scenario`/`is_hard_arch_scenario` |
| `experiments/ablation/ablation_runner.py` | 实验运行器 | `_run_single_llm` 加 MemoryBank 只读检索 |
| `experiments/ablation/cli.py` | CLI 入口 | `_prepare_group_scenarios` 重写架构组采样 |
| `experiments/ablation/safety_group.py` | 安全性组实验 | 删死代码 (`_compute_judge_consistency`, `_has_secondary_judge`, `secondary_scores` 参数) |
| `experiments/ablation/report.py` | 报告生成 | 安全组加 `statistical_note` |
| `experiments/ablation/feedback_simulator.py` | 反馈模拟 | 重写 `simulate_feedback`，加 `_compute_alignment` 等辅助函数 |
| `experiments/ablation/personalization_group.py` | 个性化组实验 | 传 `driving_context`，处理 None 反馈 |
| `experiments/ablation/AGENTS.md` | 消融文档 | 删双 Judge 未启用段落，更新假设段 |
| `tests/experiments/` | 消融测试 | 同步更新 |

---

### 任务 1：架构组场景分类 + 指标分层

**文件：**
- 修改：`experiments/ablation/architecture_group.py`

- [ ] **步骤 1：删 `is_arch_scenario` 和 `is_hard_arch_scenario`**

删两个函数。不再按场景过滤——场景分配交由 `cli.py:_prepare_group_scenarios` 处理。

- [ ] **步骤 2：加 `classify_complexity(dims) → bool`**

```python
def classify_complexity(dims: dict) -> bool:
    """判断场景是否复杂：highway OR 高疲劳 OR 过载。

    阈值与 _io.get_fatigue_threshold() 对齐。
    用于架构组 2×2 的指标分层。
    """
    return (
        dims.get("scenario") == "highway"
        or float(dims.get("fatigue_level", 0)) > get_fatigue_threshold()
        or dims.get("workload") == "overloaded"
    )
```

- [ ] **步骤 3：重写 `compute_quality_metrics` 按复杂度分层**

```python
def compute_quality_metrics(
    scores: list[JudgeScores], results: list[VariantResult]
) -> dict:
    """计算决策质量指标，按场景复杂度分层。"""
    # 建立 scenario_id → complexity 映射
    # results 中需有 synthesis_dims 或等价来源……
```

接口思路：从 `results` 重建 scenario dims 映射，分组为 simple/complex，各组内按 variant 计算指标。`_comparison` 也拆为 `comparison_simple` 和 `comparison_complex`。

- [ ] **步骤 4：更新 `make_architecture_config`——`scenario_filter` 设为恒真**

```python
def make_architecture_config() -> GroupConfig:
    return GroupConfig(
        group_name="architecture",
        variants=[Variant.FULL, Variant.SINGLE_LLM],
        scenario_filter=lambda s: True,  # 场景分配由 cli.py 负责
        metrics_computer=compute_quality_metrics,
        post_hook=_stage_scores_hook,
    )
```

- [ ] **步骤 5：更新导入——确保 `get_fatigue_threshold` 可用，更新类型导入**

保留或添加 `from ._io import get_fatigue_threshold`（`classify_complexity` 需要）。移除不再使用的导入。

- [ ] **步骤 6：Commit**

```bash
git add experiments/ablation/architecture_group.py
git commit -m "refactor(ablation): 2x2 architecture group with complexity-stratified metrics"
```

---

### 任务 2：架构组 SingleLLM 记忆检索

**文件：**
- 修改：`experiments/ablation/ablation_runner.py`

- [ ] **步骤 1：`_run_single_llm` 加 MemoryBank 只读检索**

在 LLM generate 前插入：

```python
memory_context = ""
try:
    mm = get_memory_module()
    mem_results = await mm.search(scenario.user_query, top_k=5, user_id=user_id)
    if mem_results:
        memory_context = "; ".join(
            r.content.get("text", "") for r in mem_results if hasattr(r, "content")
        )
except Exception:
    logger.debug("Memory search failed for SingleLLM (non-fatal): %s", scenario.id)
```

注入 `user_msg` JSON：
```python
user_msg_data = {"query": scenario.user_query, "context": scenario.driving_context}
if memory_context:
    user_msg_data["memory_context"] = memory_context
user_msg = json.dumps(user_msg_data, ensure_ascii=False)
```

- [ ] **步骤 2：Commit**

```bash
git add experiments/ablation/ablation_runner.py
git commit -m "feat(ablation): add memory retrieval to SingleLLM variant"
```

---

### 任务 3：架构组场景采样重排

**文件：**
- 修改：`experiments/ablation/cli.py`

- [ ] **步骤 1：`_prepare_group_scenarios` 重写架构组采样**

```python
if "architecture" in groups_to_run:
    from .architecture_group import classify_complexity

    remaining = [s for s in all_scenarios if s.id not in used_ids]
    complex_scenarios = [s for s in remaining if s.synthesis_dims and classify_complexity(s.synthesis_dims)]
    simple_scenarios = [s for s in remaining if not s.synthesis_dims or not classify_complexity(s.synthesis_dims)]

    # 先取复杂场景（至多 25），再补简单场景至 50
    n_complex = min(25, len(complex_scenarios))
    n_simple = min(50 - n_complex, len(simple_scenarios))
    sampled = (
        sample_scenarios(complex_scenarios, n_complex, stratify_key=arch_stratum, min_per_stratum=1, seed=seed + 1)
        + sample_scenarios(simple_scenarios, n_simple, stratify_key=arch_stratum, min_per_stratum=1, seed=seed + 2)
    )
    group_scenarios["architecture"] = sampled
    used_ids |= {s.id for s in sampled}
```

移除旧逻辑中 `is_arch_scenario` 的导入和调用。

- [ ] **步骤 2：更新 `cli.py` 导入——加 `classify_complexity`**

- [ ] **步骤 3：Commit**

```bash
git add experiments/ablation/cli.py
git commit -m "refactor(ablation): reallocate architecture scenarios for 2x2"
```

---

### 任务 4：安全性组死代码清理

**文件：**
- 修改：`experiments/ablation/safety_group.py`

- [ ] **步骤 1：删 `_has_secondary_judge` 函数（原 L96-98）**

- [ ] **步骤 2：删 `_compute_judge_consistency` 函数（原 L101-135）**

- [ ] **步骤 3：删 `_JUDGE_CONSISTENCY_WARN_THRESHOLD` 和 `_JUDGE_STABILITY_THRESHOLD` 常量**

- [ ] **步骤 4：简化 `compute_safety_metrics` 签名——移除 `secondary_scores` 参数**

签名变为：
```python
def compute_safety_metrics(
    scores: list[JudgeScores],
    results: list[VariantResult],
) -> dict:
```

- [ ] **步骤 5：删除 `judge_consistency` 计算分支（原 L82-92）**

删整段：
```python
judge_consistency = (
    _compute_judge_consistency(scores, secondary_scores)
    if _has_secondary_judge() and secondary_scores
    else {}
)
if judge_consistency.get("unstable_ratio", 0) > _JUDGE_CONSISTENCY_WARN_THRESHOLD:
    logger.warning(...)
metrics["_judge_consistency"] = judge_consistency
```

- [ ] **步骤 6：删 `os` 导入（不再需要）**

- [ ] **步骤 7：Commit**

```bash
git add experiments/ablation/safety_group.py
git commit -m "refactor(ablation): remove dead code (secondary judge path)"
```

---

### 任务 5：AGENTS.md 死代码段落清理

**文件：**
- 修改：`experiments/ablation/AGENTS.md`

- [ ] **步骤 1：删除第 24 行 "双 Judge 未启用" 段落**

删除：
```
`compute_safety_metrics()` 接受 `secondary_scores` 参数，内部调用 `_has_secondary_judge()`（检查 `SECONDARY_JUDGE_MODEL` 环境变量）和 `_compute_judge_consistency()` 计算双 Judge 一致性。但运行时无调用方传入 `secondary_scores`（`run_group` 传 2 参，`cli.py` 亦如此），该支线暂未启用。
```

- [ ] **步骤 2：更新架构组描述——说明 2×2 设计**

架构组章节新增：实验含简单和复杂两类场景，指标按复杂度分层报告。

- [ ] **步骤 3：Commit**

```bash
git add experiments/ablation/AGENTS.md
git commit -m "docs(ablation): update AGENTS.md - remove dead code refs, add 2x2 desc"
```

---

### 任务 6：安全性组统计标注 + 报告

**文件：**
- 修改：`experiments/ablation/report.py`
- 修改：`experiments/ablation/AGENTS.md`

- [ ] **步骤 1：`report.py` 安全组条目加 `statistical_note`**

```python
if name == "safety":
    comparison = gr.metrics.get("_comparison", {})
    no_rules = comparison.get("no-rules", {})
    no_prob = comparison.get("no-prob", {})
    worst_p = max(
        comparison.get("_wilcoxon", {}).get("no-rules", {}).get("p_value", 1),
        comparison.get("_wilcoxon", {}).get("no-prob", {}).get("p_value", 1),
    )
    worst_d = max(
        abs(no_rules.get("cohens_d", 0)),
        abs(no_prob.get("cohens_d", 0)),
    )
    summary[name]["statistical_note"] = {
        "note": (
            f"合规率 8pp 提升（Full 66% vs NO_RULES 58%），"
            f"但 Cohen's d={worst_d:.2f}, Wilcoxon p={worst_p:.2f}，"
            "未达统计显著（α=0.05）。建议 n=200+ 复验。"
        ),
        "cohens_d": round(worst_d, 2),
        "p_value": round(worst_p, 2),
        "significant": worst_p < 0.05,
    }
```

- [ ] **步骤 2：AGENTS.md 安全性组假设段加统计标注**

- [ ] **步骤 3：Commit**

```bash
git add experiments/ablation/report.py experiments/ablation/AGENTS.md
git commit -m "feat(ablation): add statistical significance annotation to safety group report"
```

---

### 任务 7：个性化组反馈模型重写

**文件：**
- 修改：`experiments/ablation/feedback_simulator.py`
- 修改：`experiments/ablation/personalization_group.py`

- [ ] **步骤 1：`feedback_simulator.py` 加辅助函数**

```python
def _get_fatigue(driving_context: dict | None) -> float:
    """从 driving_context 安全提取疲劳度。"""
    if not isinstance(driving_context, dict):
        return 0.5
    driver = driving_context.get("driver", {})
    if not isinstance(driver, dict):
        return 0.5
    fatigue = driver.get("fatigue_level", 0.5)
    return float(fatigue) if isinstance(fatigue, (int, float)) else 0.5


def _get_workload(driving_context: dict | None) -> str:
    """从 driving_context 安全提取工作负荷。"""
    if not isinstance(driving_context, dict):
        return "normal"
    driver = driving_context.get("driver", {})
    if not isinstance(driver, dict):
        return "normal"
    wl = driver.get("workload", "normal")
    return str(wl) if isinstance(wl, str) else "normal"


def _compute_alignment(decision: dict, stage: str, stages: dict | None = None) -> float:
    """决策与阶段偏好的对齐度。保持二值 [0,1] 以保可复现。

    high-freq: should_remind=True → 1.0, else 0.0
    silent: should_remind=False OR is_emergency=True → 1.0, else 0.0
    visual-detail: has_visual_content → 1.0, else 0.0
    mixed: 0.5
    """
    if stage == "mixed":
        return 0.5
    if stage == "high-freq":
        return 1.0 if decision.get("should_remind") else 0.0
    if stage == "silent":
        if not decision.get("should_remind"):
            return 1.0
        return 1.0 if decision.get("is_emergency") else 0.0
    if stage == "visual-detail":
        return 1.0 if has_visual_content(decision, stages=stages) else 0.0
    return 0.5
```

- [ ] **步骤 2：重写 `simulate_feedback`**

```python
def simulate_feedback(
    decision: dict,
    stage: str,
    rng: random.Random,
    *,
    stages: dict | None = None,
    scenario_id: str = "",
    driving_context: dict | None = None,
) -> Literal["accept", "ignore"] | None:
    """模拟用户反馈——三要素模型。

    1. 对齐度：决策与阶段偏好匹配程度
    2. 噪声：用户偶发误反馈，概率 = 0.1 + fatigue * 0.2
    3. 反馈概率：用户实际给出反馈的概率 = 0.8 - workload/fatigue penalty

    Returns: "accept" / "ignore" / None（无反馈）
    """
    alignment = _compute_alignment(decision, stage, stages)
    fatigue = _get_fatigue(driving_context)
    workload = _get_workload(driving_context)

    noise = 0.1 + fatigue * 0.2  # [0.1, 0.3]
    fb_prob = 0.8
    if workload == "overloaded":
        fb_prob -= 0.2
    if fatigue > get_fatigue_threshold():
        fb_prob -= 0.1
    fb_prob = max(0.3, fb_prob)  # [0.3, 0.8]

    if rng.random() < noise:
        return "accept" if rng.random() < 0.5 else "ignore"
    if rng.random() > fb_prob:
        return None
    return "accept" if alignment > 0.5 else "ignore"
```

- [ ] **步骤 3：更新导入——加 `_get_fatigue`、`_get_workload`、`_compute_alignment`**

`get_fatigue_threshold` 从 `_io` 导入。

- [ ] **步骤 4：`personalization_group.py` 传 `driving_context` + 处理 None**

```python
action = simulate_feedback(
    vr.decision,
    stage_name,
    rng,
    stages=vr.stages,
    scenario_id=scenario.id,
    driving_context=scenario.driving_context,
)
if action is not None:
    await update_feedback_weight(
        runner.base_user_id,
        vr.event_id,
        action,
        task_type=task_type,
    )
```

- [ ] **步骤 5：Commit**

```bash
git add experiments/ablation/feedback_simulator.py experiments/ablation/personalization_group.py
git commit -m "feat(ablation): rewrite feedback model with noise + feedback prob + alignment"
```

---

### 任务 8：更新测试

**文件：**
- 修改：`tests/experiments/test_personalization.py`
- 修改：`tests/experiments/test_ablation_runner.py`
- 其他相关测试

- [ ] **步骤 1：检查现有测试中引用已删除函数者，更新或删除**

`is_hard_arch_scenario` 和 `is_arch_scenario` 若被测试引用，替换或删除相关测试。

- [ ] **步骤 2：运行全量测试确认无回归**

```bash
uv run pytest tests/experiments/ -x -q
```

预期：全部通过（或需修复的失败）。

- [ ] **步骤 3：Commit**

```bash
git add tests/experiments/
git commit -m "test(ablation): update tests for ablation fixes"
```
