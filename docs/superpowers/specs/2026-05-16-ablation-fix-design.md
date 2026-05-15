# 消融实验修复设计

## 背景

系统分析发现消融实验三组存在以下问题：
- 架构组测错场景总体（简单而非复杂）+ 混淆记忆变量
- 死代码多处未清理（is_hard_arch_scenario, secondary_scores 等）
- 安全性组统计显著性质疑未标注
- 个性化组反馈模拟过于简化

## 1. 架构组 2×2 全因子设计

### 问题

`is_arch_scenario` 过滤条件排除高速/高疲劳/过载，导致架构组仅在简单场景下比较 Full vs SingleLLM。假设是"Full 在复杂场景优于 SingleLLM"，但实测的是简单场景。结果（SingleLLM 4.88 vs Full 2.90, d=2.58）仅反映简单场景下的差异。

同时 `_run_single_llm` 不调用 MemoryBank，Full 走完整流水线含记忆检索——混淆了"架构"与"有无记忆"两个变量。

### 方案

**不变**：Variant 枚举（FULL / SINGLE_LLM）。复杂度是场景属性，非变体属性。

**场景分类**：新增 `classify_complexity(synthesis_dims) → bool`：
```python
def classify_complexity(dims: dict) -> bool:
    """复杂场景定义：highway OR 高疲劳(>阈值) OR 过载。
    
    疲劳阈值来自 app.agents.rules.get_fatigue_threshold()（由 _io.py 封装），
    与安全性组规则引擎使用同一阈值源。
    """
    return (
        dims["scenario"] == "highway"
        or float(dims["fatigue_level"]) > get_fatigue_threshold()
        or dims["workload"] == "overloaded"
    )
```

**场景分配重排**（`cli.py:_prepare_group_scenarios`）：
1. Safety 取 50 safety_relevant
2. Architecture 从剩余 pool 中：先分配复杂场景（至多 25，不足取全部），再分配简单场景补至共 50。若 pool 总数 <50，取全部可用
3. Personalization 取剩余

**指标分层**：`compute_quality_metrics` 按 `classify_complexity` 拆分为 `metrics["simple"]` 和 `metrics["complex"]`，各含独立 Cohen's d + Bootstrap CI + Wilcoxon。

**记忆变量解混**：`_run_single_llm` 中增加 MemoryBank 只读检索（search 不 write）。检索结果注入方式：在 `user_msg` JSON 中增加 `"memory_context"` 键，内容为 `search(query=scenario.user_query, top_k=5)` 的摘要文本。不修改 system prompt。此方式与 Full 变体中 `_format_memory_hints` 的注入路径对齐——前者通过 system prompt 注入，后者通过 user msg 注入，但内容等价（均为 top-k 检索摘要）。

### 文件变动

| 文件 | 变动 |
|------|------|
| `architecture_group.py` | 删 `is_arch_scenario`/`is_hard_arch_scenario`，加 `classify_complexity`，重写 `compute_quality_metrics` |
| `ablation_runner.py` | `_run_single_llm` 加 MemoryBank 检索 |
| `cli.py` | `_prepare_group_scenarios` 重写架构组采样逻辑 |

## 2. 死代码清理

### 问题

- `is_hard_arch_scenario` 定义未用
- `compute_safety_metrics` 含 `secondary_scores` 参数但无调用方传值
- `_compute_judge_consistency` / `_has_secondary_judge` 完整逻辑但从未执行
- `_JUDGE_CONSISTENCY_WARN_THRESHOLD` / `_JUDGE_STABILITY_THRESHOLD` 常量未用
- AGENTS.md 中"双 Judge 未启用"段落过期

### 方案

全部删除。`compute_safety_metrics` 签名简化，移除 `secondary_scores` 和相关分支。

### 文件变动

| 文件 | 变动 |
|------|------|
| `safety_group.py` | 删 5 项（2 函数 + 2 常量 + `judge_consistency` 分支） |
| `experiments/ablation/AGENTS.md` | 删 24 行"双 Judge 未启用"段落 |

## 3. 安全性组统计标注

### 问题

合规率 8pp 提升（Full 66% vs NO_RULES 58%）但 Cohen's d=-0.19, Wilcoxon p=0.18——未达统计显著。输出报告未标注。

### 方案

`report.py` summary.json 中安全组条目加 `"statistical_note"` 字段，结构化为：

```python
"statistical_note": {
    "note": "合规率 8pp 提升（Full 66% vs NO_RULES 58%），但 Cohen's d=-0.19, Wilcoxon p=0.18，未达统计显著（α=0.05）。建议 n=200+ 复验。",
    "cohens_d": -0.19,
    "p_value": 0.18,
    "significant": False
}
```

AGENTS.md 假设段更新。

### 文件变动

| 文件 | 变动 |
|------|------|
| `report.py` | `render_report` 安全组加 statistical_note |
| `experiments/ablation/AGENTS.md` | 更新假设段 |

## 4. 个性化组反馈模型重写

### 问题

现模型：阶段硬规则 + mixed 50% 随机。过于简化——无噪声、无反馈缺失、无上下文感知。

### 方案

三要素模型：

```python
def simulate_feedback(decision, stage, rng, *, stages=None, scenario_id="", driving_context=None):
    # alignment 基于现有 _decision_matches_stage 逻辑（阶段硬规则）：
    # high-freq: should_remind=True → 1.0, else 0.0
    # silent: should_remind=False OR is_emergency=True → 1.0, else 0.0
    # visual-detail: has_visual_content(decision, stages=stages) → 1.0, else 0.0
    # mixed: 不对齐评估，alignment = 0.5（中立）
    # 保持二值 [0,1] 不模糊扩展——简单可复现
    alignment = _compute_alignment(decision, stage, stages)  # [0,1]
    
    fatigue = _get_fatigue(driving_context)
    workload = _get_workload(driving_context)
    
    noise = 0.1 + fatigue * 0.2          # [0.1, 0.3]
    fb_prob = 0.8 - (0.1 if overloaded else 0) - (0.1 if high_fatigue else 0)  # [0.3, 0.8]
    
    if rng.random() < noise:
        return "accept" if rng.random() < 0.5 else "ignore"  # 用户误反馈
    if rng.random() > fb_prob:
        return None  # 无反馈，跳过权重更新
    return "accept" if alignment > 0.5 else "ignore"
```

**调用方**：`run_personalization_group` 处理 None 返回值（跳过 `update_feedback_weight`），传 `driving_context`。

### 文件变动

| 文件 | 变动 |
|------|------|
| `feedback_simulator.py` | 重写 `simulate_feedback`，加 `_compute_alignment`、`_get_fatigue`、`_get_workload` |
| `personalization_group.py` | 传 `driving_context`，处理 None |

## 不涉及变动的文件

- `types.py`：Variant 枚举不变
- `protocol.py`：GroupConfig 模式不变
- `_io.py`：不变
- `scenario_synthesizer.py`：不变
- `judge.py`：不变
- `preference_metrics.py`：不变
- `metrics.py`：不变
