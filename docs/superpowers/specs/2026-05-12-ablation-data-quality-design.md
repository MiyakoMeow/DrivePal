# 消融实验数据质量优化设计

## 背景

消融实验 pipeline（合成 → 抽样 → 运行 → 评分 → 指标 → 报告）存在五个已识别问题：

1. `expected_decision` 字段未被任何代码使用（死数据）
2. 合成 prompt 硬编码了与规则引擎一致的安全约束（有偏合成）
3. 安全组 `safety_stratum` 不含 `task_type`（分层粒度不足）
4. 架构组 Cohen's d / Bootstrap CI 未接入（待实现）
5. Judge 默认分 3 的占比不可观测（区分度风险）

## 方案

### 第 1 节：场景合成——移除 expected_decision

**变更文件**：`scenario_synthesizer.py`

**做法**：

- 从 `SCENARIO_PROMPT_TEMPLATE` 中删除 `expected_decision` JSON 块（line 90-95）、`expected_task_type` 字段（line 96）
- 删除疲劳度倾向规则（line 100）——此规则与规则引擎一致，引入循环论证
- 保留 task_type 匹配指引（原 line 101），改写为不带"必须"的引导语："user_query 倾向于匹配 task_type（meeting→会议提醒, travel→导航/路线, shopping→购物, contact→联系人, other→一般问题）"
- 保留多样性指引（原 line 102）不变
- prompt 最终仅要求 LLM 返回 `driving_context` + `user_query`
- `_synthesize_one` 中 `data.get("expected_decision", {})` 保持，新数据该字段为空 dict

**向后兼容**：

- 旧 JSONL 含 `expected_decision` → `load_scenarios` 读入 dict → 无代码读取 → 无影响
- `Scenario.expected_decision` 类型不变（`dict`）
- 如需重合成：手动删除旧 JSONL，幂等跳过基于 dim_id

### 第 2 节：安全组分层——扩展 stratum

**变更文件**：`safety_group.py`, `cli.py`

**做法**：

- `safety_stratum` 末尾追加 `d["task_type"]`
- stratum 形如 `highway+meeting`、`city_driving+high_fatigue+travel` 等
- `cli.py` 中安全组 `min_per_stratum` 从 2 调为 1

**min_per_stratum=1 的理由**：

安全相关排列约 240/360。默认合成 260 场景中约 150-180 为安全相关，扩展 stratum 后约 30-40 个有效 stratum。50 场景抽 50 个，min_per_stratum=1 保证覆盖所有 stratum。变体间比较在同一场景内配对，不依赖 stratum 内样本量。

### 第 3 节：架构组 Cohen's d 补全

**变更文件**：`architecture_group.py`

**做法**：

`compute_quality_metrics()` 末尾新增一行：

```python
metrics["_comparison"] = compute_comparison(scores)
```

`compute_comparison` 已在 `metrics.py` 中完整实现（Cohen's d + Bootstrap CI + Wilcoxon signed-rank）。

### 第 4 节：Judge 默认分统计

**变更文件**：`cli.py`

**做法**：

`_print_step_summary()` 从 `metrics["_judge_degradation"]` 读取 `degraded` 标志和 ratio，复用同一阈值（`DEGRADATION_THRESHOLD = 0.5`）。`_judge_only` 路径已有相同逻辑（`cli.py:221`），全量运行路径需对齐。

不改变评分逻辑本身——默认分 3 是合理容错。

## 变更规模

| 文件 | 改动 |
|------|------|
| `scenario_synthesizer.py` | ~10 行（删除 prompt 段落 + 改写一行指引） |
| `safety_group.py` | ~2 行 |
| `architecture_group.py` | ~1 行 |
| `cli.py` | ~5 行 |
| `metrics.py` | 不变 |
| `judge.py` | 不变 |
| `types.py` | 不变 |

总 ~20 行改动，无新增文件。

## 未解决问题

1. **旧场景重合成**：需手动删除旧 JSONL 才能用新 prompt 重合成。幂等跳过基于 dim_id，不覆盖已有数据。
2. **安全组 min_per_stratum**：取 1 保证覆盖、取 2 保证每层统计功效。当前推荐 1。如未来扩大场景池至全排列（360），可改回 2。
