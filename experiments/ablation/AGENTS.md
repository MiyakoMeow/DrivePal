# 消融实验

三组消融实验，验证非记忆组件独立贡献。`python -m experiments.ablation` 运行。

与 VehicleMemBench（记忆系统对比）互不重复，共同构成完整实验体系。

## 安全性组：规则引擎 + 概率推断

**问题**：规则引擎和概率推断对安全决策的贡献？

| 要素 | 说明 |
|------|------|
| 自变量 | 规则引擎(开/关)、概率推断(开/关) |
| 因变量 | 安全合规率（Judge 口径 + 客观口径）、规则拦截率、Judge 1-5分、Cohen's d（overall_score + safety_score 两维度） |
| 变体 | Full / -Rules / -Prob / -Safety（规则+概率双双关闭） |
| 场景 | 50个安全关键场景（highway/fatigue>阈值/overloaded） |

NO_RULES 禁用 `apply_rules`（软提示）+ `postprocess_decision`（硬后处理），测“LLM无硬约束下自觉遵守安全规则的能力”。NO_SAFETY 同时禁用规则引擎和概率推断，测完全无安全机制时的基线表现。合规率基于后处理后决策。

评价指标：Judge 安全合规率(safety_score≥4，所有变体)、客观合规率(modifications 空=合规，仅 FULL/NO_PROB；NO_RULES/NO_SAFETY 不可得)、规则拦截率、违规类型分布、Cohen's d + Bootstrap CI + Wilcoxon（overall_score 和 safety_score 各一组统计）。

假设：-Rules 合规率低于 Full（Cohen's d > 0.2），但 n=50 的统计 power 有限（α=0.05），预期可能未达统计显著。结果须标注 p 值和效应量，避免过度解读趋势。

## 架构组：三Agent流水线 vs 单LLM

**问题**：三Agent结构化流水线 vs 单LLM，决策质量差异？

| 要素 | 说明 |
|------|------|
| 自变量 | 决策架构(三Agent/单LLM) |
| 因变量 | 决策质量分、中间阶段评分、延迟 |
| 变体 | Full(三阶段) / SingleLLM(单次调用合并prompt) |
| 场景 | 50个多样化场景（含简单和复杂两类）。简单：city_driving/traffic_jam/parked + 低疲劳 + 非过载；复杂：highway/高疲劳/过载 |

两侧均经 `postprocess_decision` 后处理（控制规则维度）。两变体均启用 MemoryBank 检索（解混"架构 vs 有无记忆"）。指标按复杂度分层：`metrics["simple"]` 和 `metrics["complex"]` 各含 Full/SingleLLM 的聚合指标（均分、延迟等），对应统计比较（Cohen's d、Bootstrap CI、Wilcoxon）分别在 `comparison_simple` 和 `comparison_complex` 中。

评价指标：Judge 1-5分、Context/Task/Decision各阶段评分、P50/P90延迟、Cohen's d + Bootstrap CI + Wilcoxon。

假设：Full在复杂场景中决策质量显著优于 SingleLLM。

## 个性化组：反馈学习

**问题**：反馈学习能否使决策逐步贴近用户偏好？

| 要素 | 说明 |
|------|------|
| 自变量 | 反馈学习(开/关) |
| 因变量 | 偏好匹配率、权重收敛速度、收敛稳定性 |
| 变体 | Full(动态权重自适应步长 0.05-0.3，起始 0.1) / -Feedback(固定0.5) |
| 设计 | 32轮(4阶段×8轮)，场景不足 32 时按比例缩小 |

评价指标：偏好匹配率、权重收敛速度、收敛稳定性、决策分歧度。

假设：Full在偏好切换后3-5轮内权重收敛；-Feedback匹配率接近随机。

`extract_task_type()` 按 type/task_type/task_attribution 三级fallback兜底LLM字段名不一致。
`pers_stratum()` 使用合成维度 `task_type`（非 LLM 输出 `expected_task_type`），与 `safety_stratum`/`arch_stratum` 一致，保证分层确定性。

## Checkpoint 续跑

`run_batch()` 利用 JSONL checklist 支持中断续跑：

- `load_checkpoint(path)` 读取已有结果，返回 `(已完成的(scenario_id,variant)集合, VariantResult列表, 最后一条 extra 状态 | None)`
- `append_checkpoint(path, vr, extra=None)` 每变体完成后追加写入。`extra` 字段用于持久化模块级可变状态（如反馈自适应步长）
- 运行时跳过 `existing_ids` 中已完成的组合，仅跑未完成的变体
- 安全组/架构组 checkpoint 路径即 `results.jsonl`；个性化组使用 `.checkpoint.jsonl`（独立存储反馈自适应状态），续跑不停写同一文件
- 场景/变体范围变更时自动过滤旧 checkpoint 数据
- 个性化组 checkpoint 额外记录反馈自适应步长状态（`export_state()` + `weight_history`），续跑时自动恢复反馈状态并跳过已完成变体，避免重复应用反馈导致权重偏离。注意：若在 FULL 变体后、NO_FEEDBACK 变体前中断，恢复的反馈状态可能滞后一回合（FULL 变体反馈更新未持久化），该偏差于 32 回合实验中可忽略

## CLI

`python -m experiments.ablation` 支持：

| 选项 | 说明 |
|------|------|
| `--group {safety,architecture,personalization,all}` | 实验组，默认 all |
| `--synthesize-only` | 仅合成场景，不运行实验 |
| `--judge-only` | 仅重新评分（复用已有 results.jsonl） |
| `--data-dir` | 数据目录，默认 `data/experiments` |
| `--seed` | 随机种子（覆写 `ABLATION_SEED`），默认 42 |
| `--run-id` | 运行标识符，缺省自动生成 `%Y%m%d_%H%M%S_%f_{seed}`（含微秒） |

`--group personalization` 串行执行（依赖 MemoryBank 权重状态顺序累积）；其他组并发。`--judge-only` 缺省复用最新运行目录。

## 场景合成

360维度组合(scenario×fatigue×workload×task_type×has_passengers) → LLM批量合成260场景 → 精选~132：
- 安全50（scenario × safety_condition 分层，safety_condition 为概念名——`safety_stratum()` 将 scenario + fatigue + workload 组合成复合键，非代码字面字段）
- 多样化50（scenario×task_type分层）
- 个性化32（task_type分层）

合成 prompt 含 `expected_decision` 字段（should_remind / is_emergency / allowed_channels / reminder_content / timing），由 `_build_scenario` 提取写入 `Scenario`。

## LLM-as-Judge

- 模型：优先 `model_groups.judge`，回退 default
- 盲评：不看 expected_decision 和 modifications，仅看最终 decision + 场景条件评分
- 中位数：每场景评3次取中位数
- 容错：ChatError/JSONDecodeError等 → 默认分3
- 退化检测：默认分3占比>50% 标记 degraded；任意单一分数值占比>80%（如全5分）亦触发
- 统计：Bootstrap CI(n=10000, α=0.05) + Wilcoxon signed-rank
