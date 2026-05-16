# 实验正确性修复设计

日期：2026-05-16

## 概述

前序分析在消融实验与 VehicleMemBench 集成代码中发现六项问题。本文档定义五项修复 + 一项不动，覆盖 `experiments/ablation/` 和 `experiments/vehicle_mem_bench/`。

## 修复项

### 1. 安全性消融新增 safety_score 维度的统计检验

**问题**：`compute_comparison` 与 `wilcoxon_test` 固定基于 `overall_score`。安全性组实验的核心问题是"规则/概率对安全合规的贡献"，但统计显著性检验（Cohen's d, Bootstrap CI, Wilcoxon p）测的是综合决策质量，可能掩盖安全维度的真实效应。

**修复**：

- `metrics.py` 新增 `compute_safety_score_comparison(scores)`，镜像 `compute_comparison` 结构，但收集 `safety_score` 而非 `overall_score`。内含 Cohen's d、Bootstrap CI（n=10000, α=0.05）、Wilcoxon signed-rank，以及 `_wilcoxon` 键。
- `safety_group.py` 的 `compute_safety_metrics` 增加 `_safety_comparison` 指标，与现有 `_comparison`（overall_score 维度）并列。
- `report.py` 的 `render_report` 同步读取两组统计，在 `statistical_note` 中分 `"overall_score"` 和 `"safety_score"` 两组标注。

### 2. 合规率拆分客观/主观两口径

**问题**：`objective_compliance_rate` 对 FULL/NO_PROB 用规则引擎 modifications（客观），对 NO_RULES/NO_SAFETY 回退 Judge safety_score≥4（主观）。两种度量不可直接比较。

**修复**：

- `safety_group.py` 的 `compute_safety_metrics` 新增 `judge_compliance_rate` 字段：对所有变体统一用 Judge `safety_score ≥ 4` 判定。
- `objective_compliance_rate` 仅对 FULL/NO_PROB 有效；NO_RULES/NO_SAFETY 设为 `None`（显式标记"不可得"）。
- `report.py` 合规率描述分别引用两字段，标明口径。

### 3. 适配器记忆格式与内部 MemoryBank 对齐

**问题**：VehicleMemBench 评测中适配器 `format_search_results` 产 `[score=0.852] text`；AgentWorkflow 中 `MemoryBankStore.format_search_results` 产按 source 分组、含 memory_strength、编号的富格式。两组实验给 LLM 的记忆格式不一致。

**修复**：

- `adapter.py` 的 `format_search_results` 改为按 `source` 分组、标注 `memory_strength`。格式：`N. [memory_strength=M] content_A; content_B`。
- 与 `MemoryBankStore.format_search_results` 输出风格对齐（但适配器无 store 实例，在 adapter 内复制简单分组逻辑）。
- `SearchResult.event` 的 `source`、`memory_strength` 字段可直接使用——已在 `store.py` 的构造中提供。

### 4. 场景合成 prompt 增加 expected_decision 字段

**问题**：`scenario_synthesizer.py` 的 prompt 模板未要求 LLM 生成 `expected_decision`。`Scenario.expected_decision` 恒为 `{}`。当前 Judge 盲评不用此字段，但未来若需客观合规率与 Judge 相关性校验，无可参考基准。

**修复**：

- `SCENARIO_PROMPT_TEMPLATE` 的 JSON schema 中增加 `expected_decision` 对象：
  ```json
  "expected_decision": {
    "should_remind": true/false,
    "is_emergency": true/false,
    "allowed_channels": ["audio"] 或 ["audio","visual"],
    "reminder_content": {"text": "摘要", "display_text": "", "detailed": ""},
    "timing": "immediate" 或 "at_time"
  }
  ```
- 与 `Scenario` 数据类 `expected_decision: dict` 对齐，`load_scenarios` 中 `Scenario(**d)` 自动展开。

### 5. Cohen's d 零方差时报告容错

**问题**：`cohens_d` 在两组件本均为常量且均值不等时返回 `±inf`。报告层直接显示 `d=inf`，可读性差。

**修复**：

- `report.py` 的 `render_report` 中，统计描述生成时检测 `math.isinf(d)`，显示 `"N/A (zero variance)"` 替代 `"inf"`。
- `cohens_d` 函数逻辑不变——零方差返回 inf 在数学上正确。

## 不动项

### VehicleMemBench `skipped` 死代码

`eval_utils.py:367` 中 `skipped` 恒为 `False`。此在外部项目 VehicleMemBench 中，非 DrivePal 引入。`exact_match` 计算在"期望零变化"场景下仍正确。不修。

## 影响范围

| 文件 | 修改 |
|------|------|
| `experiments/ablation/metrics.py` | 新增 `compute_safety_score_comparison` |
| `experiments/ablation/safety_group.py` | 拆分合规率字段，引用新统计函数 |
| `experiments/ablation/report.py` | 读取两组统计，Cohen's d inf 容错 |
| `experiments/vehicle_mem_bench/adapter.py` | `format_search_results` 增强格式 |
| `experiments/ablation/scenario_synthesizer.py` | prompt 模板增 expected_decision |
| `experiments/ablation/AGENTS.md` | 同步更新安全性组指标描述 |
| `experiments/vehicle_mem_bench/AGENTS.md` | 记录格式对齐变更 |

## 不变文件

`experiments/ablation/architecture_group.py`、`personalization_group.py`、`preference_metrics.py`、`feedback_simulator.py`、`judge.py`、`types.py`、`_io.py`、`protocol.py`、`ablation_runner.py`——统计逻辑与本修复无关。

`VehicleMemBench/` 下所有文件——不动。

## 测试

现有测试 `tests/` 不在本次影响范围内（实验中代码无对应单元测试）。修改后通过 ruff check + ty check 确保无 lint/type 回归。
