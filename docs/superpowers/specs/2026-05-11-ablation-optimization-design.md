# 消融实验方法论优化设计

## 背景

`experiments/ablation/` 实现三组消融实验（安全性 / 架构 / 个性化），验证系统各组件独立贡献。
代码审查发现多处方法论缺陷和文档不一致，影响实验结论有效性和论文可信度。

## 变更范围

仅修改 `experiments/ablation/` 目录下文件及 `AGENTS.md` 中消融实验相关章节。
不涉及 `app/` 主代码逻辑。

---

## 第 1 节：场景合成——移除规则泄漏

### 问题

`CHANNEL_HINT_MAP` 将规则引擎通道约束硬编码进合成 prompt（`scenario_synthesizer.py:87-92`），
LLM 生成 `expected_decision` 时直接套用规则 → 循环论证。

### 改动

1. **删除 `CHANNEL_HINT_MAP`**（4 条映射）
2. **简化合成 prompt**：移除 `{channel_hint}` 引用，`expected_decision.allowed_channels` 不再引导
3. **保留安全性直觉提示**：高疲劳/过载 → 少打扰（自然用户期望，非系统规则）
4. **`_is_safety_relevant` → `_compute_safety_relevant(dim)`**：从合成维度计算，不读 LLM 输出

```python
def _compute_safety_relevant(dim: dict) -> bool:
    scenario = dim["scenario"]
    if scenario == "highway":
        return True
    fatigue = dim["fatigue_level"]
    if isinstance(fatigue, (int, float)) and fatigue > get_fatigue_threshold():
        return True
    return dim["workload"] == "overloaded"
```

阈值统一调用 `_io.get_fatigue_threshold()`，不引入额外常量。

---

## 第 2 节：Judge——移除 expected_decision，修复盲评

### 问题

- `expected_decision` 传入 Judge prompt（`judge.py:82-87`），引导评分方向
- shuffle 用 `sha256(id)` 确定性种子（`judge.py:156-158`），同场景永远相同顺序

### 改动

1. **移除 `expected_decision`**——`score_variant` 的 `user_msg` 不再包含 `scenario.expected_decision`
2. **盲评 shuffle**——`score_batch` 的 RNG 改为：

```python
seed = int(os.environ.get("ABLATION_SEED", "0"))
rng = random.Random(seed if seed else None)
```

`ABLATION_SEED` 非零 → 确定性复现；零/未设置 → 时间种子真随机。

---

## 第 3 节：个性化组——场景不复用

### 问题

`personalization_scenarios[i % len(...)]` 场景不足时取模复用，
MemoryBank 跨阶段累积交互，污染权重学习。

### 改动

1. **不取模**——场景不足时按比例截断轮数
2. `run_personalization_group` 入口动态调整 `STAGES` 边界：

```python
available = len(personalization_scenarios)
effective_rounds = min(available, 32)
stage_size = effective_rounds // 4
stages = [
    ("high-freq", 0, stage_size),
    ("silent", stage_size, stage_size * 2),
    ("visual-detail", stage_size * 2, stage_size * 3),
    ("mixed", stage_size * 3, effective_rounds),
]
```

3. 正常情况（260 合成 ≥ 132 分配）不会触发截断

---

## 第 4 节：统计检验——Bootstrap CI + Wilcoxon

### 问题

仅 Cohen's d 效应量，无显著性检验。

### 改动

`metrics.py` 新增：

1. **`bootstrap_ci(group_a, group_b, n_bootstrap=10000, alpha=0.05)`**
   - 对均值差做 bootstrap 置信区间
   - 返回 `{ci_lower, ci_upper, significant}`

2. **`wilcoxon_test(scores_a, scores_b)`**
   - Wilcoxon signed-rank test（非参数，适合 ordinal 1-5 配对比较）
   - 按 scenario_id 配对 FULL vs 消融变体
   - 返回 `{statistic, p_value}`

3. `compute_comparison` / `compute_safety_comparison` 调用并注入 metrics dict

### 依赖

新增 `scipy` 依赖（`scipy.stats.wilcoxon`）。

---

## 第 5 节：分层键——改用合成维度

### 问题

`safety_stratum` / `arch_stratum` 读 LLM 生成的 `driving_context`，
LLM 可能生成错误 scenario/fatigue → 分层错位。

### 改动

1. **`Scenario` 新增 `synthesis_dims: dict`** 字段
   - 存储 `{scenario, fatigue_level, workload, task_type, has_passengers}`
   - 来自 `_build_dimension_combinations()`，不依赖 LLM

2. **`safety_stratum` / `arch_stratum` / `is_arch_scenario`** 改读 `synthesis_dims`

```python
def safety_stratum(s: Scenario) -> str:
    d = s.synthesis_dims
    parts = [d["scenario"]]
    if d["fatigue_level"] > FATIGUE_THRESHOLD:
        parts.append("high_fatigue")
    if d["workload"] == "overloaded":
        parts.append("overloaded")
    return "+".join(parts)
```

3. 合成时写入 `synthesis_dims`，加载时兼容旧数据（缺失时从 `id` 解析——id 格式为 `{scenario}_{fatigue_level}_{workload}_{task_type}_{has_passengers}`）

---

## 第 6 节：AGENTS.md 更新 + 死代码清理

### 文档更新

| 项 | 旧 | 新 |
|----|-----|-----|
| 合成数量 | ~120 场景 | ~260 场景（360 维度随机抽取） |
| 个性化轮数 | 20 轮（4×5） | 32 轮（4×8），不足时按比例截断 |
| 个性化场景 | 各类型各 4 | 32 场景，task_type 分层（min_per_stratum=2） |
| 人工校准 / Cohen's κ | 描述为已有 | 移除——标注为"未实现，后续工作" |
| "3 轮 prompt 调整" | 描述为已有 | 移除 |
| Judge 描述 | 参考 expected_decision | 不参考，盲评支持确定性/随机双模式 |
| 安全组场景分配 | 含所有 city_driving | 仅 highway / 高疲劳 / 过载 |
| 统计检验 | 无 | 新增 Bootstrap CI + Wilcoxon |

### 死代码清理

1. 删除 `judge.py` 中 `compute_cohens_kappa`（~60 行）
2. 统一疲劳阈值引用——三文件共用 `_io.get_fatigue_threshold()`
3. 删除 `CHANNEL_HINT_MAP`
4. `_is_safety_relevant` → `_compute_safety_relevant(dim)`

---

## 不变更

- `app/` 主代码不动
- 三组实验的整体结构不变（安全组 3 变体 / 架构组 2 变体 / 个性化组 2 变体）
- Judge 的规则表内容不变
- 场景合成的 360 维度组合不变
- `ablation_runner.py` 的 ContextVar 控制逻辑不变

## 文件变更清单

| 文件 | 操作 |
|------|------|
| `experiments/ablation/types.py` | 新增 `synthesis_dims` 字段 |
| `experiments/ablation/scenario_synthesizer.py` | 删除 `CHANNEL_HINT_MAP`，改 `_compute_safety_relevant`，写入 `synthesis_dims` |
| `experiments/ablation/judge.py` | 移除 `expected_decision`，修复 shuffle，删除 `compute_cohens_kappa` |
| `experiments/ablation/metrics.py` | 新增 `bootstrap_ci`、`wilcoxon_test`，更新 `compute_comparison` |
| `experiments/ablation/safety_group.py` | `safety_stratum` 改读 `synthesis_dims`，删除本地 `FATIGUE_THRESHOLD` |
| `experiments/ablation/architecture_group.py` | `arch_stratum` / `is_arch_scenario` 改读 `synthesis_dims`，删除本地常量 |
| `experiments/ablation/personalization_group.py` | 移除取模复用，动态截断轮数 |
| `experiments/ablation/_io.py` | 无变更（已是共享点） |
| `experiments/ablation/cli.py` | 适配新字段/函数签名 |
| `AGENTS.md` | 更新消融实验章节 |
| `pyproject.toml` | 新增 `scipy` 依赖 |
