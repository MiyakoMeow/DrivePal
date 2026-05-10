# 消融实验修复设计

## 概述

修复消融实验模块 13 个实现问题，确保实验正确运行、指标计算准确、结果可复现。

## 修复清单

### 一、数据完整性——`round_index` 闭环

**文件：** `experiments/ablation/_io.py`, `experiments/ablation/cli.py`

- `_io.py` `dump_variant_results_jsonl()` record 加 `round_index` 字段
- `cli.py` `_load_variant_results()` 重建时加 `round_index=d.get("round_index", 0)`

### 二、个性化组 Judge 评分集成

**文件：** `experiments/ablation/personalization_group.py`, `experiments/ablation/cli.py`

- `run_personalization_group()` 签名加 `judge: Judge` 参数
- 运行完所有变体后，按 scenario 分组调用 `judge.score_batch()`，3 次取中位数
- `cli.py` `_run_personalization_experiment` 传入 judge 实例
- `--judge-only` 中 personalization 分支：加载结果 → `judge.score_batch()` → 计算指标

### 三、场景合成并发化

**文件：** `experiments/ablation/scenario_synthesizer.py`

- `asyncio.Semaphore(8)` 控制并发
- `asyncio.gather` 并行发起，Semaphore 控制 inflight 数
- `asyncio.Lock` 保护 JSONL 追加写入
- 保持幂等跳过逻辑

### 四、`_compute_stability` 指标修正

**文件：** `experiments/ablation/personalization_group.py`

- 当前：每轮所有权重平均值的标准差
- 修正：偏好切换后，跟踪**上一阶段权重最高的类型**（目标类型）在新阶段连续 5 轮的权重标准差。选取规则：
  - high-freq → silent 切换时：取 high-freq 最后轮最高权重类型（用户刚学会偏好此类型，切换后此权重应下降）
  - silent → visual-detail 切换时：取 silent 最后轮最高权重类型（同上逻辑——跟踪刚学会的类型在新阶段的振荡）
  - visual-detail → mixed 切换时：取 visual-detail 最后轮最高权重类型
  - 若权重全为 0.5（初始状态），则跳过该切换点（不参与稳定性计算）
  - 并列最高时取类型名字典序最小者（确定性消歧）

### 五、场景字段名对齐 + 校准集骨架

**文件：** `experiments/ablation/scenario_synthesizer.py`, `experiments/ablation/judge.py`

- `SCENARIO_PROMPT_TEMPLATE` 中 `expected_decision` 字段：
  - `channel` -> `allowed_channels`（list）
  - `is_urgent` -> `is_emergency`
- `scenario_synthesizer.py` 加 `load_calibration_set()` 函数骨架——`raise NotImplementedError("校准数据文件尚未创建，需人工标注后提供路径")`。校准数据文件格式：JSONL，每行含 `scenario_id` + `human_label`（含 safety_score/reasonableness_score/overall_score 人工标注）
- `judge.py` 加 `compute_cohens_kappa(judge_scores: list[JudgeScores], human_labels: dict[str, dict[str, int]]) -> float` 函数。`human_labels` 结构：`{scenario_id: {"overall_score": int}}`。使用 **quadratic weighted Cohen's κ**（平方加权，1-5 ordinal 评分适用）。计算公式：κ = (po - pe) / (1 - pe)，权重矩阵 w_ij = ((i - j) / (k - 1))²

### 六、增量 checkpoint + 环境变量加固

**文件：** `experiments/ablation/ablation_runner.py`

- `_set_env`：`_original_env[k] = os.environ.get(k)` —— 存 None 而非 ""，restore 时判 None → pop
- `run_batch`：每变体完成即追加写 JSONL（而非全部完成后）
- 重跑时跳过已有 `(scenario_id, variant.value)` 组合

### 七、`_compute_overfitting_gap` 语义修正

**文件：** `experiments/ablation/personalization_group.py`

- 函数重命名为 `_compute_decision_divergence`
- 改为比较 FULL vs NO_FEEDBACK 所有决策字段的差异项数（非仅 `should_remind`）
- `_compute_matching_rate` 中 mixed 阶段 `_decision_matches_stage` 返回 None（新增行为：原函数对所有阶段返回 bool，现 mixed 阶段返回 None 表"不适用"），`_compute_matching_rate` 处理方式：None 不计入分母（即跳过该项，不参与该阶段的匹配率分子分母）
- 实现前需 `grep` 审计 `_decision_matches_stage` 所有调用点，确保无其他调用方依赖 bool 返回值

### 八、`simulate_feedback` 注释增强

**文件：** `experiments/ablation/personalization_group.py`

- 加 docstring 说明：实验简写版，直接操作 `strategies.toml`，不走正式 feedback API
- 标注 TODO：可选集成正式 `submitFeedback` mutation

## 影响范围

| 文件 | 变更类型 |
|------|----------|
| `_io.py` | 加 `round_index` 字段 |
| `cli.py` | 重载修复 + personalization Judge 调用 |
| `personalization_group.py` | Judge 集成 + 指标修正 + 语义修正 |
| `scenario_synthesizer.py` | 并发化 + 字段对齐 + 校准集骨架 |
| `ablation_runner.py` | 环境变量加固 + 增量 checkpoint |
| `judge.py` | `compute_cohens_kappa()` |

## 不变项

- 无新增文件
- 无 API 变更
- `types.py`、`report.py`、`safety_group.py`、`architecture_group.py`、`metrics.py` 不改
- 对外接口（CLI 参数、JSONL 输出结构）保持兼容

## 测试

- 增 `test_round_index_roundtrip` —— `_io.py` 写入/重载闭环
- 增 `test_compute_stability_target_type` —— 新指标计算
- 增 `test_decision_divergence` —— 替代 overfitting_gap
- 增 `test_cohens_kappa` —— Judge 与人工一致率
- 现有测试全量保持通过
