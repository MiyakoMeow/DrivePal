# 消融实验修正设计

## 概述

修正上一轮代码审查发现的消融实验设计的五个问题。

---

## 1. 架构组复杂度分层：预分配法

### 问题

`classify_complexity()` 与 `_compute_safety_relevant()` 使用相同判定条件（highway / fatigue>threshold / overloaded）。`_prepare_group_scenarios()` 中安全组先抽取全部 safety_relevant 场景，架构组仅从剩余场景中抽样——导致架构组的"complex"场景与"simple"场景同质。

### 方案

预分配法。`_prepare_group_scenarios()` 改为两轮分配：

1. 扫描全量场景，标记 `is_complex = classify_complexity(s.synthesis_dims)`
2. 安全组从 complex 池中抽取 n=50 safety_relevant 场景
3. 架构组从**剩余 complex + 全部 simple** 中抽取 50 场景，目标 25 complex + 25 simple
4. 个性化组从剩余池抽取 32

若 complex 场景不足安全组+架构组分，按以下降级：
- 安全组优先，取 min(50, len(complex_pool))
- 架构组取剩余 complex + simple 补至 50
- n 在实验结果中明确标注

### 修改文件

- `cli.py` → `_prepare_group_scenarios()` 重写
- `safety_group.py` → `safety_stratum()` 不变

### 不影响

- `safety_group.py` / `architecture_group.py` 其余逻辑不变
- 统计检验路径不变
- Judge 评分不变

---

## 2. 安全组补 NO_RULES+NO_PROB 联合消融细胞

### 问题

2×2 全因子（规则引擎 × 概率推断）缺 (OFF, OFF) 细胞，交互效应不可检。

### 方案

新增 `Variant.NO_SAFETY`（同时禁用规则引擎和概率推断）。

`types.py` 枚举追加：
```python
class Variant(StrEnum):
    FULL = "full"
    NO_RULES = "no-rules"
    NO_PROB = "no-prob"
    NO_SAFETY = "no-safety"  # 新增
    SINGLE_LLM = "single-llm"
    NO_FEEDBACK = "no-feedback"
```

`run_variant()` 追加处理：
```python
elif variant == Variant.NO_SAFETY:
    set_ablation_disable_rules(True)
    set_probabilistic_enabled(False)
```

`make_safety_config()` variants 追加 `Variant.NO_SAFETY`。

`compute_safety_comparison()` / `compute_safety_metrics()` 无需修改——它们已按 variant 自动分组。

### 修改文件

- `types.py` → Variant 枚举
- `ablation_runner.py` → `run_variant()` 追加 elif
- `safety_group.py` → `make_safety_config()` variants 列表

### 测试新增

- `test_ablation_runner.py` → 增加 `test_no_safety_variant` 验证双 ContextVar 同时 set

---

## 3. 个性化组：步长自适应

### 问题

32 轮 4 阶段 + ±0.1 固定步长。每阶段 8 轮不足以在偏好切换后收敛：理论上需 ~10 轮将权重从 0.5 推至 1.0（考虑反馈概率 0.6-0.8），实际每阶段仅 8 轮。

### 方案

**步长自适应**。`update_feedback_weight()` 中 delta 非固定 ±0.1，根据最近 3 次反馈一致性动态调整：

- 最近 3 次反馈同向（全部 accept 或全部 ignore）→ delta × 1.5（加速收敛）
- 最近 3 次反馈出现反向 → delta × 0.5（怀疑振荡，保守退半步）
- clamp: [0.05, 0.3]，起始步长 0.1

实现：

```python
# 按 task_type 跟踪最近 N 次反馈方向 + 当前步长
# 模块级 dict——不安全如需并发调用。
# 当前调用链路：personalization_group 串行运行，安全。
_current_delta: dict[str, float] = {}  # task_type → 当前步长
_recent_feedback: dict[str, list[int]] = {}  # task_type → [+1/-1]*N

def _adaptive_delta(task_type: str, action: str) -> float:
    delta = _current_delta.get(task_type, 0.1)
    history = _recent_feedback.setdefault(task_type, [])
    direction = 1 if action == "accept" else -1
    history.append(direction)
    if len(history) > 3:
        history.pop(0)
    if len(history) < 2:
        _current_delta[task_type] = 0.1
        return 0.1  # 信息不足，默认步长
    # 全部同向 → 加速（当前步长 × 1.5）
    if all(d == direction for d in history):
        delta = min(0.3, delta * 1.5)
    # 出现反向 → 保守（当前步长 × 0.5）
    else:
        delta = max(0.05, delta * 0.5)
    _current_delta[task_type] = delta
    return delta
```

**轮数**：论文已有数据基于 32 轮 4 阶段·固定步长。修复在新实验中启用自适应步长，论文中标注"固定步长版本用于 4.7.4 报告，自适应步长在后续验证中收敛速度提升 X"。

### 修改文件

- `feedback_simulator.py` → `update_feedback_weight()` 改用 `_adaptive_delta`
- `feedback_simulator.py` → 新增 `_adaptive_delta()` + `_recent_feedback` 模块级 dict

### 测试新增

- `test_personalization.py` → 新增 `test_adaptive_delta_convergence` 验证同向加速、反向减速

---

## 4. 安全合规率客观测量

### 问题

合规率当前依赖 Judge `safety_score >= 4`，但可客观从 `modifications` 列表计算。

### 方案

`compute_safety_metrics()` 增加 `objective_*` 指标：

```python
objective_total = len(variant_results)
objective_compliant = sum(
    1 for r in variant_results if not r.modifications
)
objective_rate = objective_compliant / objective_total if objective_total else 0
```

对于 NO_RULES 变体（modifications 始终为空），objective_rate 回退到 Judge-based compliance_rate，保持可比性。

输出 metrics 格式：
```python
metrics[variant] = {
    "n": n,
    "compliance_rate": ...,          # Judge-based（保留）
    "objective_compliance_rate": ..., # 新增：基于 modifications 的客观率
    "objective_compliant_n": ...,
    "interception_rate": ...,
    "avg_overall_score": ...,
}
```

report.py 的 statistical_note 改用 objective_compliance_rate 计算极差。

### 修改文件

- `safety_group.py` → `compute_safety_metrics()`
- `report.py` → `render_report()` 改用客观合规率

---

## 5. 补测试覆盖率

### 测试清单

| 测试 | 文件 | 说明 |
|------|------|------|
| `test_no_safety_variant` | `test_ablation_runner.py` | NO_SAFETY → 规则和概率推断双双关闭 |
| `test_adaptive_delta_convergence` | `test_personalization.py` | 同向 3 次 → 步长 0.15，反向 → 0.05 |
| `test_objective_compliance` | `test_ablation_optimization.py` | FULL modifications 空=合规，非空=违规 |
| `test_prepare_group_scenarios_complexity` | `test_ablation_optimization.py` | 架构组含足够 complex 场景 |

---

## 文件变更汇总

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `experiments/ablation/types.py` | 修改 | Variant 枚举追加 NO_SAFETY |
| `experiments/ablation/ablation_runner.py` | 修改 | run_variant() 追加 elif |
| `experiments/ablation/safety_group.py` | 修改 | metrics 加 objective_*，config variants 加 NO_SAFETY |
| `experiments/ablation/cli.py` | 修改 | _prepare_group_scenarios 复杂度预分配 |
| `experiments/ablation/feedback_simulator.py` | 修改 | update_feedback_weight 步长自适应 |
| `experiments/ablation/report.py` | 修改 | 改用 objective_compliance_rate |
| `tests/experiments/test_ablation_runner.py` | 修改 | 加 test_no_safety_variant |
| `tests/experiments/test_personalization.py` | 修改 | 加 test_adaptive_delta_convergence |
| `tests/experiments/test_ablation_optimization.py` | 修改 | 加 test_objective_compliance + test_complexity_preallocation |

---

## 不做的

- 合成新场景（个性化组 64 轮方案）— 现有 132 场景够用，4 章改 3 阶段即可
- 跨模型对比（成本高，实验设计论文已承认）
- 重构整个 `_prepare_group_scenarios`（仅改分配逻辑，不动整体结构）
