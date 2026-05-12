# 消融实验

`experiments/ablation/`。三组消融实验，验证系统各组件的独立贡献。通过 `python -m experiments.ablation` 运行。

## 实验目的

VehicleMemBench 已覆盖记忆系统对比（MemoryBank vs None/Gold/Summary/Key-Value）。消融实验覆盖非记忆组件对比——验证规则引擎、四Agent流水线架构、反馈学习各自对系统决策质量的贡献。

---

## 安全性组：规则引擎 + 概率推断消融

**研究问题**：规则引擎和概率推断各自对安全决策的贡献多大？

| 要素 | 说明 |
|------|------|
| **自变量** | 规则引擎（启用/禁用）、概率推断（启用/禁用） |
| **因变量** | 安全合规率、规则拦截率、决策综合质量（Judge 1-5分） |
| **变体** | Full（启用全部）/ -Rules（禁用规则引擎）/ -Prob（禁用概率推断） |

**变体语义说明**：NO_RULES 禁用的是 `postprocess_decision`（规则引擎后处理），LLM 输出不再被安全规则强制覆盖。Judge 仍按完整规则表评分。因此 NO_RULES 测量的是"LLM 在无硬约束下自觉遵守安全规则的能力"，而非"无规则时系统的安全性"。

| **测试场景** | 50 个安全关键场景。安全相关性由合成维度计算（highway / fatigue>阈值 / overloaded）。分层键按 scenario × safety_condition（不含 task_type——安全测试不关注任务类型分布）|
| **无关变量控制** | 同一 LLM（默认模型组）、同一 MemoryBank 状态（独立 user_id）、固定随机种子、场景分层抽样 |

**评价指标**：

| 指标 | 定义 |
|------|------|
| 安全合规率 | Judge 评估决策是否违反安全约束（`safety_score ≥ 4` 为合规） |
| 规则拦截率 | Full 变体中 `postprocess_decision` 修改 LLM 输出的比例 |
| 违规类型分布 | 藏于 `_comparison` 子键下：`channel_violation` / `frequency_violation` / `non_urgent_during_fatigue` / `remind_during_overload` / `missed_urgent` |
| 决策综合质量 | Judge 1-5 分，综合安全性 + 合理性 + 用户体验 |
| Cohen's d | Full vs 各消融变体的效应量 |

**假设**：-Rules 变体安全合规率显著低于 Full（Cohen's d > 0.5）；-Prob 变体决策质量低于 Full。

---

## 架构组：四Agent流水线 vs 单LLM

**研究问题**：四 Agent 结构化流水线 vs 单 LLM 调用，决策质量差异多大？

| 要素 | 说明 |
|------|------|
| **自变量** | 决策架构（四Agent流水线 / 单LLM） |
| **因变量** | 决策质量分、JSON 结构合规率、各阶段中间质量、端到端延迟 |
| **变体** | Full（四阶段 Context→Task→Decision→Execution）/ SingleLLM（一次 LLM 调用，合并 prompt 直接输出） |
| **测试场景** | 50 个多样化场景（排除极端安全条件：fatigue ≤ 0.7, workload ≠ overloaded, scenario ≠ highway），覆盖所有 scenario × task_type 组合（排除 highway） |
| **无关变量控制** | 同一 LLM（默认模型组）、两侧均经 `postprocess_decision` 规则引擎后处理（控制规则维度）、同一场景集、固定随机种子。记忆检索为流水线架构固有组成，论文中说明此设计决策 |

**评价指标**：

| 指标 | 定义 |
|------|------|
| 决策质量分 | Judge 1-5 分，综合合理性、上下文理解、任务归因 |
| JSON 结构合规率 | 输出是否包含所有必需字段、类型正确、格式合法（待实现） |
| 中间阶段评分 | Full 的 Context（上下文准确性）/ Task（事件归因准确度）/ Decision（决策合理性）各 1-5 分，独立 Judge prompt |
| 延迟 P50 / P90 | 端到端 AgentWorkflow 耗时（ms） |
| Cohen's d | Full vs SingleLLM 效应量（`compute_comparison` 提供 Cohen's d + Bootstrap CI + Wilcoxon signed-rank） |

**假设**：Full 在复杂场景（多约束冲突）中决策质量显著优于 SingleLLM；SingleLLM 延迟更低。

---

## 个性化组：反馈学习消融

**研究问题**：反馈学习机制能否使系统决策逐步贴近用户真实偏好？

| 要素 | 说明 |
|------|------|
| **自变量** | 反馈学习（启用/禁用） |
| **因变量** | 偏好匹配率、权重收敛速度、收敛稳定性 |
| **变体** | Full（动态权重，初始 0.5，±0.1/反馈）/ -Feedback（固定权重 0.5） |
| **实验设计** | 32 轮（4 阶段 × 8 轮），场景不足时按比例截断 |
| **无关变量控制** | 同一 LLM（默认模型组）、固定场景集（32 独立场景，按 task_type 分层）、同一 MemoryBank 状态（独立 user_id，清空启动）、固定随机种子（`ABLATION_SEED`） |

**评价指标**：

| 指标 | 定义 | 量化方法 |
|------|------|---------|
| 偏好匹配率 | 决策与当前阶段期望偏好的一致比例 | 每阶段匹配数 / 该阶段总轮数 |
| 权重收敛速度 | 目标类型权重稳定所需的归一化进度 | [0,1] 归一化（越小越快），-1 表示未收敛 |
| 收敛稳定性 | 偏好切换后权重振荡幅度 | 切换后连续 5 轮权重的标准差 |
| 决策分歧度 | 混合偏好阶段 FULL vs NO_FEEDBACK 决策差异 | 所有决策字段差异比例取平均 |

**假设**：Full 在偏好切换后 3-5 轮内权重收敛至目标方向；-Feedback 匹配率在各阶段均接近随机水平。

**实现细节**：`feedback_simulator.py` 中 `extract_task_type()` 从 `stages.task` 提取任务类型时，按 `type` / `task_type` / `task_attribution` 三级键名 fallback——兜底 LLM 输出的字段名不一致问题（不同模型/温度下可能产出不同键名）。已知类型集合 `_KNOWN_TASK_TYPES` 过滤非标准值（如 "navigation"/"reminder"），避免权重绑定错误 key。

---

## 测试场景合成

360 维度组合（scenario 4 × fatigue 3 × workload 3 × task_type 5 × has_passengers 2）→ LLM 批量合成驾驶场景 → 缓存至 JSONL。精选 ~260 场景（360 维度组合随机抽取）：

- 安全关键场景 50（按 scenario×safety_condition 分层抽样，min_per_stratum=1。不含 task_type——task_type × condition 叉积可达 80 层，远超 n=50）
- 多样化场景 50（分层随机抽样，覆盖所有 scenario × task_type 组合）
- 个性化场景 32，按 task_type 分层抽样（min_per_stratum=2）

共 ~132 场景（安全 50 + 架构 50 + 个性化 32）。

每个场景含：`driving_context` + `user_query` + `expected_task_type`（来自维度组合）。`expected_decision` 字段为历史遗留（旧 JSONL 兼容），当前合成不再生成。

## LLM-as-Judge 评测

- **模型**：优先 `[model_groups.judge]`（TOML 配置），否则回退 `[model_groups.default]`
- **盲评**：Judge 不参考 expected_decision，仅依据规则表 + 场景条件评分。shuffle 支持确定性（ABLATION_SEED 非零）/ 随机（零/未设置）双模式
- **中位数**：每场景评 3 次取中位数，减少非确定性噪声
- **容错**：`ChatError` → 默认分 3；`JSONDecodeError`/`TypeError`/`ValueError` → 默认分 3
- **退化检测**：默认分 3 占比超过 50% 时标记 `degraded=True`；任一分数值占比超过 `CONCENTRATION_THRESHOLD`（0.8）时标记集中度退化。全量运行和 judge-only 两条路径均输出警告
- **分数分布报告**：`summary.json` 中含 `score_distributions` 字段（各变体均值 + 各分数段比例），辅助 Judge 校准评估
- **统计检验**：Bootstrap 置信区间（n=10000, α=0.05）+ Wilcoxon signed-rank test（按 scenario_id 配对）
- **人工校准**：人工校准为后续工作，当前未实现。

## 与 VehicleMemBench 的关系

- VehicleMemBench 覆盖记忆系统对比（MemoryBank vs None/Gold/Summary/Key-Value）
- 消融实验覆盖非记忆组件对比（规则引擎、流水线架构、反馈学习）
- 互不重复，共同构成完整实验体系
