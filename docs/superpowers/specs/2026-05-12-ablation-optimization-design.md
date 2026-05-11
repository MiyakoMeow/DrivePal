# 消融实验优化设计

## 背景

消融实验框架已实现三组实验（安全性/架构/个性化），覆盖规则引擎、四Agent流水线、反馈学习三个非记忆组件。代码审查发现 6 个实现问题 + 1 个语义问题，需在本轮优化中解决。

## 变更清单

### P1：Judge 规则动态化

**问题**：`judge.py` 的 `JUDGE_SYSTEM_PROMPT` 硬编码 7 条规则文本副本。`rules.toml` 修改后 Judge 评分标准不跟随变化，导致评分与系统实际规则不一致。

**方案**：
- `JUDGE_SYSTEM_PROMPT` 拆为固定评分指令 + `{rules_text}` 占位符
- 新增 `format_rules_for_judge(rules: list[Rule]) -> str`，从 `app.agents.rules.SAFETY_RULES`（类型 `list[Rule]`，`Rule` 定义于 `app.agents.rules`）动态生成规则描述
- `Judge.score_variant` 渲染完整 system_prompt 后传给 LLM
- 生成格式保持与当前硬编码格式一致：`规则N [name priority=X]: 描述`

**影响范围**：`experiments/ablation/judge.py`

**不改动**：评分标准段落（safety_score/reasonableness_score/overall_score 的 1-5 分定义）、"重要提示"段落——这些是手工精调的评分指令。

### P2：SingleLLM prompt 补齐

**问题**：`SINGLE_LLM_SYSTEM_PROMPT` 缺少 `is_emergency` 和 `reminder_content` 三格式结构（speakable_text/display_text/detailed）。四阶段 STRATEGY prompt 有这些字段。架构组对比不公平——SingleLLM 的信息量少于四阶段。

**方案**：在 `SINGLE_LLM_SYSTEM_PROMPT` 的策略决策部分补齐：
- `是否为紧急事件（is_emergency）`
- `reminder_content 对象，包含三种格式`（含格式说明和示例）
- 输出示例中对应补齐

**影响范围**：`app/agents/prompts.py`

### P3：Judge 中位数聚合修复

**问题**：`_median_scores` 按 `overall_score` 排序取中位数记录后直接使用该记录的全部字段。其余两次评分的 safety_score/reasonableness_score 被丢弃。名义上"3次取中位数"，实际只用了 1 次的数据。

**方案**：逐维度独立排序取中位数：
- `safety_score`：按 safety_score 排序取中位数
- `reasonableness_score`：按 reasonableness_score 排序取中位数
- `overall_score`：按 overall_score 排序取中位数
- `violation_flags` / `explanation`：取 overall_score 中位数对应记录的值

**影响范围**：`experiments/ablation/judge.py`

### P4：visual-detail 阶段判定修复

**问题**：`_has_visual_content` 检查 `decision` dict 中的 `reminder_content.display_text/detailed`。但规则引擎 `postprocess_decision` 在 postpone/only_urgent 时会清除 `reminder_content`。即使 LLM 生成了视觉内容，判定也可能失败。

**方案**：
- `_has_visual_content` 增加 `stages` 参数，优先从 `stages["decision"]` 读取（规则引擎前的 LLM 原始输出）
- `stages` 为空或无数据时 fallback 到 `decision`
- `simulate_feedback` 签名增加 `stages: dict` 参数
- 调用链 `run_personalization_group` → `simulate_feedback` 传入 `vr.stages`（`vr` 为 `VariantResult` 实例）

**影响范围**：`experiments/ablation/personalization_group.py`

### P5：场景合成默认值修正

**问题**：`synthesize_scenarios` 函数签名默认 `count=120`，但 `cli.py` 调用时传 `count=260`。函数签名默认值与实际使用不一致，误导阅读者。

**方案**：默认值改为 `count=260`。

**影响范围**：`experiments/ablation/scenario_synthesizer.py`

### P6：Cohen's d 参数方向注释

**问题**：`compute_comparison` 中 `cohens_d(overalls, baseline_overalls)` 返回 variant - baseline 方向。参数名 group_a/group_b 不暗示方向，阅读者需查函数定义才能理解。

**方案**：调用处加注释说明返回值方向语义。

**影响范围**：`experiments/ablation/metrics.py`

### S1：NO_RULES 变体语义文档

**问题**：NO_RULES 变体禁用 `postprocess_decision`（规则引擎后处理），但 Judge 仍按规则评分。实际测量的是"LLM 在无硬约束下能否自觉遵守安全规则"，不是"无规则时系统是否安全"。

**方案**：代码不变。在 `experiments/AGENTS.md` 安全性组段落增加变体语义精确定义。

**影响范围**：`experiments/AGENTS.md`

## 不做的事

- 不改变 NO_RULES 变体的实验逻辑（仅文档说明）
- 不增加新变体或新实验组
- 不修改 `rules.toml` 规则内容
- 不修改 VehicleMemBench 对接逻辑
- 不修改测试框架或 CI 工作流

## 测试策略

- P1：验证 `format_rules_for_judge` 输出格式与当前硬编码一致
- P2：验证 SingleLLM prompt 包含 is_emergency 和 reminder_content 三格式
- P3：用构造数据验证 _median_scores 逐维度中位数正确
- P4：构造 stages dict 验证 _has_visual_content 优先读 stages
- P5/P6：简单断言即可
- 现有测试不能 break
