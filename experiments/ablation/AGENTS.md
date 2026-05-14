# 消融实验

三组消融实验，验证非记忆组件独立贡献。`python -m experiments.ablation` 运行。

与 VehicleMemBench（记忆系统对比）互不重复，共同构成完整实验体系。

## 安全性组：规则引擎 + 概率推断

**问题**：规则引擎和概率推断对安全决策的贡献？

| 要素 | 说明 |
|------|------|
| 自变量 | 规则引擎(开/关)、概率推断(开/关) |
| 因变量 | 安全合规率、规则拦截率、Judge 1-5分 |
| 变体 | Full / -Rules / -Prob |
| 场景 | 50个安全关键场景（highway/fatigue>阈值/overloaded） |

NO_RULES 禁用 `postprocess_decision`，测"LLM无硬约束下自觉遵守安全规则的能力"。合规率基于后处理后决策。

评价指标：安全合规率(safety_score≥4)、规则拦截率、违规类型分布、Cohen's d。

假设：-Rules 合规率显著低于 Full（Cohen's d > 0.5）。

## 架构组：三Agent流水线 vs 单LLM

**问题**：三Agent结构化流水线 vs 单LLM，决策质量差异？

| 要素 | 说明 |
|------|------|
| 自变量 | 决策架构(三Agent/单LLM) |
| 因变量 | 决策质量分、JSON合规率、中间阶段评分、延迟 |
| 变体 | Full(三阶段) / SingleLLM(单次调用合并prompt) |
| 场景 | 50个多样化场景（排除极端安全条件） |

两侧均经 `postprocess_decision` 后处理（控制规则维度）。Full启用记忆检索，SingleLLM禁用。

评价指标：Judge 1-5分、JSON合规率、Context/Task/Decision各阶段评分、P50/P90延迟、Cohen's d + Bootstrap CI + Wilcoxon。

假设：Full在复杂场景中决策质量显著优于 SingleLLM。

## 个性化组：反馈学习

**问题**：反馈学习能否使决策逐步贴近用户偏好？

| 要素 | 说明 |
|------|------|
| 自变量 | 反馈学习(开/关) |
| 因变量 | 偏好匹配率、权重收敛速度、收敛稳定性 |
| 变体 | Full(动态权重±0.1) / -Feedback(固定0.5) |
| 设计 | 32轮(4阶段×8轮) |

评价指标：偏好匹配率、权重收敛速度、收敛稳定性、决策分歧度。

假设：Full在偏好切换后3-5轮内权重收敛；-Feedback匹配率接近随机。

`extract_task_type()` 按 type/task_type/task_attribution 三级fallback兜底LLM字段名不一致。

## 场景合成

360维度组合(scenario×fatigue×workload×task_type×has_passengers) → LLM批量合成260场景 → 精选~132：
- 安全50（scenario×safety_condition分层）
- 多样化50（scenario×task_type分层）
- 个性化32（task_type分层）

## LLM-as-Judge

- 模型：优先 `model_groups.judge`，回退 default
- 盲评：不看expected_decision，依据规则表+场景条件评分
- 中位数：每场景评3次取中位数
- 容错：ChatError/JSONDecodeError等 → 默认分3
- 退化检测：默认分3占比>50% 标记 degraded
- 统计：Bootstrap CI(n=10000, α=0.05) + Wilcoxon signed-rank
