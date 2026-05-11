# experiments - 消融实验

`ablation/` 目录。三组消融实验，验证非记忆组件贡献。通过 `python -m experiments.ablation` 运行。

VehicleMemBench 覆盖记忆系统对比，消融实验覆盖非记忆组件——互补构成完整实验体系。

## 安全性组：规则引擎 + 概率推断

| 变体 | 说明 |
|------|------|
| Full | 启用全部 |
| -Rules | 禁用规则引擎 |
| -Prob | 禁用概率推断 |

50 安全关键场景。评价：安全合规率、规则拦截率、违规类型分布、决策综合质量、Cohen's d。

## 架构组：四Agent流水线 vs 单LLM

| 变体 | 说明 |
|------|------|
| Full | 四阶段 Context→Task→Strategy→Execution |
| SingleLLM | 一次 LLM 调用，合并 prompt |

50 多样化场景（排除极端安全条件）。评价：决策质量、JSON合规率、中间阶段质量、延迟 P50/P90、Cohen's d。

## 个性化组：反馈学习

| 变体 | 说明 |
|------|------|
| Full | 动态权重（初始0.5，±0.1/反馈）|
| -Feedback | 固定权重0.5 |

20 轮交互，4 阶段偏好切换。评价：偏好匹配率、权重收敛速度/稳定性、决策分歧度。

## 测试场景

360 维度组合（scenario 4 × fatigue 3 × workload 3 × task_type 5 × has_passengers 2）→ LLM 批量合成 → JSONL 缓存。精选 ~120 场景（安全50 + 多样50 + 个性化20）。

## LLM-as-Judge

- 模型：优先 `JUDGE_MODEL`，否则回退 `[model_groups.default]`
- 盲评 + 中位数（每场景评3次）
- 容错：ChatError/JSONDecodeError → 默认分3
- 人工校准：~50 场景，Cohen's κ 验证
