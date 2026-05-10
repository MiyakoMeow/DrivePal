# 消融实验修复实现计划

> **面向 AI 代理的工作者：** 使用 subagent-driven-development 逐任务实现。步骤用复选框（`- [ ]`）跟踪进度。

**目标：** 修复消融实验模块 13 个实现问题——数据完整性、指标正确性、并发性能、环境变量安全性。

**架构：** 增量修补现有 experiments/ablation/ 下 6 个文件 + 4 个测试文件。无新增文件、无 API 变更、无外部依赖变更。

**技术栈：** Python 3.14, asyncio, dataclasses, pytest

---

## 文件结构

| 文件 | 职责 | 本计划变更 |
|------|------|-----------|
| `experiments/ablation/_io.py` | JSONL 写出工具 | 加 `round_index` 字段 |
| `experiments/ablation/cli.py` | 命令行入口 + 结果重载 | `_load_variant_results` 恢复 round_index；`--judge-only` personalization 分支 |
| `experiments/ablation/ablation_runner.py` | 变体运行 + 环境变量管理 | `_set_env`/`_restore_env` 加固；`run_batch` 增量 checkpoint |
| `experiments/ablation/personalization_group.py` | 个性化组实验 | Judge 集成 + `_compute_stability` 修正 + `_compute_decision_divergence` 重命名 + 注释增强 |
| `experiments/ablation/scenario_synthesizer.py` | 场景合成 | asyncio.Semaphore(8) 并发 + 字段名对齐 + 校准集骨架 |
| `experiments/ablation/judge.py` | LLM-as-Judge | `compute_cohens_kappa()` |
| `tests/experiments/test_io.py` | round_index 序列化/反序列化逻辑 | **新建** |
| `tests/experiments/test_personalization.py` | 稳定性、决策分歧指标 | **新建** |
| `tests/experiments/test_cohens_kappa.py` | Cohen's κ 计算 | **新建** |
| `tests/experiments/test_scenario_synthesizer.py` | 已有，增补并发相关 | 修改 |

---

### 任务 1：round_index 序列化闭环

**文件：**
- 修改：`experiments/ablation/_io.py:28-37`
- 修改：`experiments/ablation/cli.py:100-126`
- 新建：`tests/experiments/test_io.py`

- [ ] **步骤 1：`_io.py` 加 `round_index` 字段**

`_io.py:28-36`，record dict 加 `"round_index": r.round_index`：

```python
record: dict[str, Any] = {
    "scenario_id": r.scenario_id,
    "variant": r.variant.value,
    "decision": r.decision,
    "stages": r.stages,
    "latency_ms": r.latency_ms,
    "round_index": r.round_index,
}
```

- [ ] **步骤 2：`cli.py` `_load_variant_results` 恢复 `round_index`**

`cli.py:114-124`，VariantResult 构造加 `round_index=d.get("round_index", 0)`：

```python
results.append(
    VariantResult(
        scenario_id=d["scenario_id"],
        variant=variant,
        decision=d.get("decision", {}),
        result_text="",
        event_id=None,
        stages=d.get("stages", {}),
        latency_ms=d.get("latency_ms", 0),
        modifications=d.get("modifications", []),
        round_index=d.get("round_index", 0),
    )
)
```

- [ ] **步骤 3：编写测试**

`tests/experiments/test_io.py`——测试写入→加载往返保留 `round_index`：

```python
"""测试 round_index 序列化往返."""
import json
from pathlib import Path

from experiments.ablation._io import dump_variant_results_jsonl
from experiments.ablation.types import Variant, VariantResult


async def test_round_index_roundtrip(tmp_path: Path):
    """Given VariantResult with round_index=5, When dump then load, Then round_index preserved."""
    vr = VariantResult(
        scenario_id="s1",
        variant=Variant.FULL,
        decision={},
        result_text="",
        event_id=None,
        stages={},
        latency_ms=0.0,
        round_index=5,
    )
    path = tmp_path / "results.jsonl"
    await dump_variant_results_jsonl(path, [vr])

    lines = path.read_text().strip().split("\n")
    loaded = json.loads(lines[0])
    assert loaded["round_index"] == 5


async def test_round_index_default_zero(tmp_path: Path):
    """Given VariantResult with default round_index, When dump then load, Then round_index=0."""
    vr = VariantResult(
        scenario_id="s1",
        variant=Variant.FULL,
        decision={},
        result_text="",
        event_id=None,
        stages={},
        latency_ms=0.0,
    )
    path = tmp_path / "results.jsonl"
    await dump_variant_results_jsonl(path, [vr])

    lines = path.read_text().strip().split("\n")
    loaded = json.loads(lines[0])
    assert loaded["round_index"] == 0
```

- [ ] **步骤 4：运行测试验证**

```bash
uv run pytest tests/experiments/test_io.py -v
```
预期：2 passed

- [ ] **步骤 5：Commit**

```bash
git add experiments/ablation/_io.py experiments/ablation/cli.py tests/experiments/test_io.py
git commit -m "fix(ablation): preserve round_index in JSONL serialization"
```

---

### 任务 2：场景合成并发化

**文件：** `experiments/ablation/scenario_synthesizer.py`

- [ ] **步骤 1：改造 `synthesize_scenarios` 为并发版本**

核心思路：将串行 for 循环替换为 `asyncio.Semaphore(8)` + `asyncio.gather`。

接口保持：`async def synthesize_scenarios(output_path: Path, count: int = 120) -> int`。

关键变更：

```python
# 在 synthesize_scenarios 内：
sem = asyncio.Semaphore(8)
write_lock = asyncio.Lock()
existing = _load_existing_ids(output_path)
generated_count = 0
log_interval = 10

async def _synthesize_one(combo: dict) -> int:
    nonlocal generated_count
    dim_id = f"{combo['scenario']}_{combo['fatigue_level']}_{combo['workload']}_{combo['task_type']}_{combo['has_passengers']}"
    if dim_id in existing:
        return 0

    async with sem:
        prompt = _build_prompt(combo)
        try:
            raw = await chat_model.generate(
                prompt=prompt, system_prompt=SYSTEM_PROMPT, json_mode=True
            )
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON for combo %s", dim_id)
            return 0
        except ChatError:
            logger.warning("LLM call failed for combo %s", dim_id, exc_info=True)
            return 0

        driving_context = data.get("driving_context", {})
        scenario_type_val = driving_context.get("scenario", combo["scenario"])
        safety = _is_safety_relevant(driving_context)

        scenario = Scenario(
            id=dim_id,
            driving_context=driving_context,
            user_query=data.get("user_query", ""),
            expected_decision=data.get("expected_decision", {}),
            expected_task_type=data.get("expected_task_type", combo["task_type"]),
            safety_relevant=safety,
            scenario_type=scenario_type_val,
        )

        async with write_lock:
            current_total = generated_count
            if current_total >= count:
                return 0
            await _write_scenario(scenario, output_path)
            existing.add(dim_id)
            generated_count += 1

        if generated_count % log_interval == 0:
            logger.info("synthesized %d/%d scenarios", generated_count, count)
        return 1

    tasks = [_synthesize_one(c) for c in combos]
    await asyncio.gather(*tasks)
    return generated_count
```

注意：`generated_count` 用 `nonlocal` 配合 `write_lock` 保护。并发内 `count` 检查在锁内进行，避免超额合成。

- [ ] **步骤 2：增补幂等逻辑——并发下防止重复写入**

`_load_existing_ids` 在并发启动前一次性读取，`existing` 集合在并发中仅追加（`.add(dim_id)`），无删除。并发安全——写锁内先检查再写入。

- [ ] **步骤 3：运行测试验证**

```bash
uv run pytest tests/experiments/test_scenario_synthesizer.py -v
```
预期：all passed（现有测试不依赖真实 LLM）

- [ ] **步骤 4：Commit**

```bash
git add experiments/ablation/scenario_synthesizer.py
git commit -m "perf(ablation): concurrent scenario synthesis with semaphore(8)"
```

---

### 任务 3：场景字段名对齐

**文件：** `experiments/ablation/scenario_synthesizer.py`

- [ ] **步骤 1：修正 `SCENARIO_PROMPT_TEMPLATE`**

将第 62-67 行 `expected_decision` 部分从：

```json
"expected_decision": {
    "should_remind": true或false,
    "channel": "{channel_hint}",
    "content": "提醒内容中文",
    "is_urgent": true或false
}
```

改为：

```json
"expected_decision": {
    "should_remind": true或false,
    "allowed_channels": ["{channel_hint}"],
    "content": "提醒内容中文",
    "is_emergency": true或false
}
```

注意 `allowed_channels` 为列表——高速/城市/拥堵为 `["audio"]`，停车为 `["audio", "visual"]`。prompt 中 `{channel_hint}` 变 `["audio"]` 或 `["audio", "visual"]`。需同步修改 `_build_prompt` 中 `channel_hint` 拼装逻辑：

```python
CHANNEL_HINT_MAP: dict[str, str] = {
    "parked": '["audio", "visual"]',
    "highway": '["audio"]',
    "city_driving": '["audio"]',
    "traffic_jam": '["audio"]',
}
```

- [ ] **步骤 2：同步修改 prompt 注意事项**

prompt 末段注意事项 L72-76，`channel` 引用同步改为 `allowed_channels`：
- `"如果 scenario!=parked，allowed_channels 应为 ['audio']（驾驶中视觉通道被占用）"`
- `"如果 scenario==parked，allowed_channels 可用 ['audio', 'visual']"`

- [ ] **步骤 3：Commit**

```bash
git add experiments/ablation/scenario_synthesizer.py
git commit -m "fix(ablation): align expected_decision fields with Agent output format"
```

---

### 任务 4：个性化组 Judge 评分集成

**文件：** `experiments/ablation/personalization_group.py`, `experiments/ablation/cli.py`

- [ ] **步骤 1：`run_personalization_group` 签名加 `judge` 参数**

参数列表加 `*, judge: Judge`（keyword-only，放在 `seed` 之后）。

- [ ] **步骤 2：运行后按 scenario_id 分组评分**

在 `_compute_preference_metrics` 调用之前，插入 Judge 评分逻辑。用 `personalization_scenarios` 的 `scenario_map` 获取真实场景对象（含 `user_query` + `driving_context`）：

```python
# Judge 评分：按 scenario_id 分组，用真实场景对象
scenario_map = {s.id: s for s in personalization_scenarios}
scores: list[JudgeScores] = []
grouped: dict[str, list[VariantResult]] = {}
for vr in all_results:
    grouped.setdefault(vr.scenario_id, []).append(vr)
for scenario_id, scenario_vrs in grouped.items():
    batch_scores = await judge.score_batch(scenario_map[scenario_id], scenario_vrs)
    scores.extend(batch_scores)
```

- [ ] **步骤 3：GroupResult 传入 judge_scores**

```python
return GroupResult(
    group="personalization",
    variant_results=all_results,
    judge_scores=scores,  # 原为 []
    metrics=metrics,
)
```

- [ ] **步骤 4：`cli.py` `_run_personalization_experiment` 传入 judge**

```python
async def _run_personalization_experiment(...) -> GroupResult:
    runner = AblationRunner(user_id="experiment-personalization")
    judge = Judge()  # 新增
    ...
    return await run_personalization_group(
        runner,
        personalization_scenarios,
        data_dir / "results" / "personalization.jsonl",
        seed=seed,
        judge=judge,  # 新增
    )
```

- [ ] **步骤 5：`cli.py` `--judge-only` 支持 personalization 组重新评分**

`_judge_only` 中 `else` 分支（L87）改为加载 personalization 结果 → judge 评分 → 更新 metrics：

```python
else:  # personalization
    scores_for_group = []
    for sid, vrs in scenarios_for_results.items():
        scenario = scenario_by_id.get(sid)
        if scenario is None:
            continue
        batch_scores = await judge.score_batch(scenario, vrs)
        scores_for_group.extend(batch_scores)
    # personalization 组 metrics 不变（偏好匹配率等不依赖 judge 评分）
    metrics = {}  
```

- [ ] **步骤 6：Commit**

```bash
git add experiments/ablation/personalization_group.py experiments/ablation/cli.py
git commit -m "feat(ablation): integrate Judge scoring into personalization group"
```

---

### 任务 5：校准集骨架 + Cohen's κ

**文件：** `experiments/ablation/scenario_synthesizer.py`, `experiments/ablation/judge.py`

- [ ] **步骤 1：`scenario_synthesizer.py` 加 `load_calibration_set` 骨架**

```python
def load_calibration_set(path: Path) -> dict[str, dict[str, int]]:
    """加载人工校准集。尚未创建——需人工标注后提供路径。
    
    Returns: {scenario_id: {"overall_score": int}}
    """
    raise NotImplementedError(
        "校准数据文件尚未创建。需人工标注后，调用此函数并传入 JSONL 文件路径。"
        "JSONL 格式：每行 {'scenario_id': str, 'human_label': {'overall_score': int}}"
    )
```

- [ ] **步骤 2：`judge.py` 加 `compute_cohens_kappa`**

```python
def compute_cohens_kappa(
    judge_scores: list[JudgeScores],
    human_labels: dict[str, dict[str, int]],
) -> float:
    """Quadratic weighted Cohen's κ。
    
    judge_scores: Judge 为各场景各变体的评分列表
    human_labels: {scenario_id: {"overall_score": int}} 人工标注
    
    对每个 scenario_id 取 Judge 评分中位数，与人工标注计算加权 κ。
    权重矩阵：w_ij = ((i - j) / (k - 1))²，k=5（1-5 分）。
    """
    k = 5
    # 对 judge_scores 按 scenario_id 取 overall_score 中位数
    from collections import defaultdict
    by_scenario: dict[str, list[int]] = defaultdict(list)
    for js in judge_scores:
        by_scenario[js.scenario_id].append(js.overall_score)
    
    judge_median: dict[str, int] = {}
    for sid, scores in by_scenario.items():
        sorted_scores = sorted(scores)
        mid = len(sorted_scores) // 2
        judge_median[sid] = sorted_scores[mid]
    
    # 构建混淆矩阵 O_{ij}：Judge 评 i、人工评 j 的场景数
    import numpy as np
    O = np.zeros((k, k), dtype=np.int64)
    for sid, hl in human_labels.items():
        if sid not in judge_median:
            continue
        i = judge_median[sid] - 1  # 1-5 → 0-4
        j = hl["overall_score"] - 1
        O[i, j] += 1
    
    total = O.sum()
    if total == 0:
        return 1.0  # 空集，完美一致（或应返回 NaN？取 1.0 保守）
    
    # 权重矩阵
    W = np.zeros((k, k), dtype=np.float64)
    for i in range(k):
        for j in range(k):
            W[i, j] = ((i - j) / (k - 1)) ** 2
    
    # 观察一致率
    po = 1.0 - (O * W).sum() / total
    
    # 期望一致率
    row_sums = O.sum(axis=1)
    col_sums = O.sum(axis=0)
    E = np.outer(row_sums, col_sums) / total
    pe = 1.0 - (E * W).sum() / total
    
    if pe == 1.0:
        return 1.0
    return (po - pe) / (1.0 - pe)
```

- [ ] **步骤 3：编写测试**

`tests/experiments/test_cohens_kappa.py`：

```python
"""测试 Cohen's κ 计算."""
from experiments.ablation.judge import compute_cohens_kappa
from experiments.ablation.types import JudgeScores, Variant


def test_perfect_agreement():
    """Given Judge and human scores identical, κ should be 1.0."""
    judge = [
        JudgeScores("s1", Variant.FULL, 5, 5, 5, [], ""),
        JudgeScores("s2", Variant.FULL, 3, 3, 3, [], ""),
    ]
    human = {"s1": {"overall_score": 5}, "s2": {"overall_score": 3}}
    kappa = compute_cohens_kappa(judge, human)
    assert kappa == 1.0


def test_large_disagreement():
    """Given Judge always 5 but human always 1, κ should be negative or zero."""
    judge = [
        JudgeScores("s1", Variant.FULL, 5, 5, 5, [], ""),
        JudgeScores("s2", Variant.FULL, 5, 5, 5, [], ""),
    ]
    human = {"s1": {"overall_score": 1}, "s2": {"overall_score": 1}}
    kappa = compute_cohens_kappa(judge, human)
    assert kappa <= 0.0


def test_empty_inputs():
    """Given empty inputs, κ should be 1.0."""
    kappa = compute_cohens_kappa([], {})
    assert kappa == 1.0
```

- [ ] **步骤 4：运行测试验证**

```bash
uv run pytest tests/experiments/test_cohens_kappa.py -v
```
预期：3 passed

- [ ] **步骤 5：Commit**

```bash
git add experiments/ablation/scenario_synthesizer.py experiments/ablation/judge.py tests/experiments/test_cohens_kappa.py
git commit -m "feat(ablation): add Cohen's κ and calibration set skeleton"
```

---

### 任务 6：`_compute_stability` 指标修正

**文件：** `experiments/ablation/personalization_group.py`

- [ ] **步骤 1：重写 `_compute_stability`**

替换 `personalization_group.py:233-259`：

```python
def _compute_stability(weight_history: list[dict], stages: list[tuple]) -> float:
    """偏好切换后目标类型权重的平均标准差。
    
    对每个切换点（high-freq→silent, silent→visual-detail, visual-detail→mixed）：
    1. 取上一阶段最后一轮最高权重类型（目标类型）
    2. 若所有权重均为 0.5（初始态），跳过该切换点
    3. 并列最高时取类型名字典序最小者
    4. 跟踪该类型在新阶段连续 5 轮的权重，计算标准差
    5. 返回所有切换点标准差的均值
    """
    if not weight_history:
        return 0.0

    switch_points = [end for _, _, end in stages[:-1]]
    stds: list[float] = []

    for sp in switch_points:
        if sp < 1 or sp >= len(weight_history):
            continue

        # 上一阶段最后一轮权重
        prev_weights = weight_history[sp - 1].get("weights", {})
        if not prev_weights or all(abs(w - 0.5) < 0.01 for w in prev_weights.values()):
            continue  # 初始态，跳过

        # 取最高权重类型（并列取字典序最小）
        max_w = max(prev_weights.values())
        target_types = [t for t, w in prev_weights.items() if w == max_w]
        target_type = min(target_types)  # 字典序消歧

        # 跟踪新阶段 5 轮
        window = weight_history[sp : min(sp + 5, len(weight_history))]
        weights_in_window = [
            wh.get("weights", {}).get(target_type, 0.5) for wh in window
        ]
        if len(weights_in_window) < 2:
            continue

        mean = sum(weights_in_window) / len(weights_in_window)
        variance = sum((w - mean) ** 2 for w in weights_in_window) / len(weights_in_window)
        stds.append(variance ** 0.5)

    return sum(stds) / len(stds) if stds else 0.0
```

- [ ] **步骤 2：编写测试**

`tests/experiments/test_personalization.py` 中加：

```python
"""测试 _compute_stability 指标."""
from experiments.ablation.personalization_group import _compute_stability


def test_stability_no_oscillation():
    """Given weights stable after switch, stability should be near 0."""
    wh = [
        {"weights": {"meeting": 0.9, "travel": 0.5}},  # round 1
        {"weights": {"meeting": 0.9, "travel": 0.5}},  # round 2 (switch point=2)
        {"weights": {"meeting": 0.3, "travel": 0.5}},  # round 3
        {"weights": {"meeting": 0.3, "travel": 0.5}},  # round 4
        {"weights": {"meeting": 0.3, "travel": 0.5}},  # round 5
        {"weights": {"meeting": 0.3, "travel": 0.5}},  # round 6
        {"weights": {"meeting": 0.3, "travel": 0.5}},  # round 7
    ]
    # Switch at round=2 (high-freq→silent), target=meeting (max weight at round 1)
    stages = [("high-freq", 0, 2), ("silent", 2, 7)]
    result = _compute_stability(wh, stages)
    assert result == 0.0  # meeting weight stable at 0.3 after switch


def test_stability_with_oscillation():
    """Given weights oscillate after switch, stability should be > 0."""
    wh = [
        {"weights": {"meeting": 0.9, "travel": 0.5}},  # round 1
        {"weights": {"meeting": 0.9, "travel": 0.5}},  # round 2
        {"weights": {"meeting": 0.3, "travel": 0.5}},  # round 3
        {"weights": {"meeting": 0.7, "travel": 0.5}},  # round 4 (jumps up)
        {"weights": {"meeting": 0.2, "travel": 0.5}},  # round 5 (jumps down)
        {"weights": {"meeting": 0.6, "travel": 0.5}},  # round 6
        {"weights": {"meeting": 0.4, "travel": 0.5}},  # round 7
    ]
    stages = [("high-freq", 0, 2), ("silent", 2, 7)]
    result = _compute_stability(wh, stages)
    assert result > 0.0


def test_stability_initial_state_skipped():
    """Given all weights at 0.5 (initial), switch point should be skipped."""
    wh = [
        {"weights": {"meeting": 0.5, "travel": 0.5}},  # round 1
        {"weights": {"meeting": 0.5, "travel": 0.5}},  # round 2
        {"weights": {"meeting": 0.5, "travel": 0.5}},  # round 3
    ]
    stages = [("high-freq", 0, 2), ("silent", 2, 3)]
    result = _compute_stability(wh, stages)
    assert result == 0.0  # all skipped
```

- [ ] **步骤 3：运行测试**

```bash
uv run pytest tests/experiments/test_personalization.py::test_stability -v
```
预期：3 passed

- [ ] **步骤 4：Commit**

```bash
git add experiments/ablation/personalization_group.py tests/experiments/test_personalization.py
git commit -m "fix(ablation): correct _compute_stability to track target type weight"
```

---

### 任务 7：`_compute_overfitting_gap` → `_compute_decision_divergence`

**文件：** `experiments/ablation/personalization_group.py`

- [ ] **步骤 1：审计 `_decision_matches_stage` 调用点**

```bash
rg "_decision_matches_stage" experiments/ablation/personalization_group.py
```

结果：仅 `_compute_matching_rate:178` 一处调用。安全修改。

- [ ] **步骤 2：修改 `_decision_matches_stage`——mixed 阶段返回 None**

在函数开头加：

```python
def _decision_matches_stage(decision: dict, stage: str) -> bool | None:
    """单条决策是否匹配阶段偏好。mixed 阶段返回 None 表示不适用。"""
    if stage == "mixed":
        return None
    ...
```

- [ ] **步骤 3：修改 `_compute_matching_rate`——处理 None 返回值**

L173-179 改为：

```python
for i, wh in enumerate(weight_history):
    stage = wh["stage"]
    if i >= len(full_results):
        break
    decision = full_results[i].decision
    matched = _decision_matches_stage(decision, stage)
    if matched is None:
        continue  # mixed 阶段不参与匹配率计算
    stage_matches.setdefault(stage, []).append(matched)
```

- [ ] **步骤 4：重命名 `_compute_overfitting_gap` → `_compute_decision_divergence`**

函数名全局替换。实现改为比较 FULL vs NO_FEEDBACK 所有决策字段差异项数：

```python
def _compute_decision_divergence(
    results: list[VariantResult],
    weight_history: list[dict],
) -> float:
    """FULL vs NO_FEEDBACK 在 mixed 阶段的决策分歧度。
    
    对每个 mixed 轮次，比较两个变体的 decision dict 差异字段数，
    取所有轮次的平均。越高说明 FULL 学偏了。
    """
    mixed_rounds = [
        i for i, wh in enumerate(weight_history) if wh.get("stage") == "mixed"
    ]
    if not mixed_rounds:
        return 0.0

    mixed_indices = {i + 1 for i in mixed_rounds}
    full_mixed = [
        r for r in results
        if r.variant == Variant.FULL and r.round_index in mixed_indices
    ]
    no_fb_mixed = [
        r for r in results
        if r.variant == Variant.NO_FEEDBACK and r.round_index in mixed_indices
    ]

    # 按 round_index 配对
    full_by_round = {r.round_index: r for r in full_mixed}
    no_fb_by_round = {r.round_index: r for r in no_fb_mixed}
    common_rounds = set(full_by_round) & set(no_fb_by_round)
    if not common_rounds:
        return 0.0

    divergences: list[float] = []
    for ri in common_rounds:
        d1 = full_by_round[ri].decision
        d2 = no_fb_by_round[ri].decision
        # 计数差异字段
        all_keys = set(d1) | set(d2)
        diff_count = sum(1 for k in all_keys if d1.get(k) != d2.get(k))
        divergences.append(diff_count / max(1, len(all_keys)))

    return sum(divergences) / len(divergences)
```

- [ ] **步骤 5：更新 `_compute_preference_metrics` 返回的 key**

`"overfitting_gap"` → `"decision_divergence"`。

- [ ] **步骤 6：编写测试**

`tests/experiments/test_personalization.py` 续加：

```python
"""测试 _compute_decision_divergence."""
from experiments.ablation.personalization_group import _compute_decision_divergence
from experiments.ablation.types import Variant, VariantResult


def test_decision_divergence_no_difference():
    """Given identical decisions, divergence should be 0."""
    vr_full = VariantResult("s1", Variant.FULL, {"should_remind": True}, "", None, {}, 0, round_index=17)
    vr_nofb = VariantResult("s1", Variant.NO_FEEDBACK, {"should_remind": True}, "", None, {}, 0, round_index=17)
    wh = [{"stage": "mixed"} for _ in range(20)]  # round 17 = index 16
    result = _compute_decision_divergence([vr_full, vr_nofb], wh)
    assert result == 0.0


def test_decision_divergence_with_difference():
    """Given different decisions, divergence should be > 0."""
    vr_full = VariantResult("s1", Variant.FULL, {"should_remind": True, "channel": "audio"}, "", None, {}, 0, round_index=17)
    vr_nofb = VariantResult("s1", Variant.NO_FEEDBACK, {"should_remind": False, "channel": "visual"}, "", None, {}, 0, round_index=17)
    wh = [{"stage": "mixed"} for _ in range(20)]
    result = _compute_decision_divergence([vr_full, vr_nofb], wh)
    assert result > 0.0
```

- [ ] **步骤 7：运行测试**

```bash
uv run pytest tests/experiments/test_personalization.py -v
```
预期：5 passed（3 stability + 2 divergence）

- [ ] **步骤 8：Commit**

```bash
git add experiments/ablation/personalization_group.py tests/experiments/test_personalization.py
git commit -m "refactor(ablation): rename overfitting_gap to decision_divergence with semantic fix"
```

---

### 任务 8：增量 checkpoint + 环境变量加固

**文件：** `experiments/ablation/ablation_runner.py`

- [ ] **步骤 1：加固 `_set_env` 和 `_restore_env`**

`ablation_runner.py:39-50`，将 `setdefault` 改为直接存原值（None 表示 key 不存在）：

```python
def _set_env(self, **kwargs: str) -> None:
    for k, v in kwargs.items():
        self._original_env.setdefault(k, os.environ.get(k))  # None if absent
        os.environ[k] = v

def _restore_env(self) -> None:
    for k, v in self._original_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    self._original_env.clear()
```

关键变更：`os.environ.get(k)` 无默认值时返回 `None`（key 不存在）。restore 时判 `v is None` → pop。

- [ ] **步骤 2：`run_batch` 增量写 JSONL**

`run_batch` 签名加 `checkpoint_path: Path | None = None`。每变体完成即追加写：

```python
async def run_batch(
    self, scenarios: list[Scenario], variants: list[Variant],
    *, checkpoint_path: Path | None = None,
) -> list[VariantResult]:
    results: list[VariantResult] = []
    for scenario in scenarios:
        for variant in variants:
            # 检查已有 checkpoint，跳过已完成的组合
            if checkpoint_path and checkpoint_path.exists():
                existing = _load_checkpoint_ids(checkpoint_path)
                if (scenario.id, variant.value) in existing:
                    continue
            vr = await self.run_variant(scenario, variant)
            results.append(vr)
            if checkpoint_path:
                await _append_checkpoint(checkpoint_path, vr)
    return results
```

`_load_checkpoint_ids` 和 `_append_checkpoint` 为模块级辅助函数——读取 JSONL 中已有 `(scenario_id, variant)` 对，追加写单条 VariantResult。

- [ ] **步骤 3：safety/architecture/personalization 三组传 `checkpoint_path`**

各组的 `run_*_group` 函数中 `run_batch` 调用加 `checkpoint_path=output_path`。`run_personalization_group` 不走 `run_batch`，需单独在循环内加 checkpoint 写入（用 `_append_checkpoint`）。

- [ ] **步骤 4：Commit**

```bash
git add experiments/ablation/ablation_runner.py
git add experiments/ablation/safety_group.py experiments/ablation/architecture_group.py experiments/ablation/personalization_group.py
git commit -m "fix(ablation): harden env var mgmt and add incremental checkpoint"
```

---

### 任务 9：`simulate_feedback` 注释增强

**文件：** `experiments/ablation/personalization_group.py`

- [ ] **步骤 1：补 docstring**

在 `simulate_feedback` 函数体前加完整 docstring：

```python
def simulate_feedback(
    decision: dict, stage: str, rng: random.Random
) -> Literal["accept", "ignore"]:
    """模拟用户反馈——根据阶段偏好决定 accept 或 ignore。

    实验简写版：直接操作 strategies.toml 的 reminder_weights，
    不走正式 submitFeedback mutation（不写 feedback.jsonl、不更新 memory_strength）。
    
    TODO: 可选集成正式 submitFeedback API。

    #126 后策略 Agent 输出 is_emergency（非 is_urgent），allowed_channels 列表（非 channel 字符串）。
    """
```

- [ ] **步骤 2：Commit**

```bash
git add experiments/ablation/personalization_group.py
git commit -m "docs(ablation): document simulate_feedback as experimental shim"
```

---

### 任务 10：全量回归 + lint + type check

- [ ] **步骤 1：ruff lint + format**

```bash
uv run ruff check --fix
uv run ruff format
```
预期：无错误

- [ ] **步骤 2：ty 类型检查**

```bash
uv run ty check
```
预期：无新增类型错误

- [ ] **步骤 3：全量测试**

```bash
uv run pytest tests/ -v
```
预期：所有现有测试 + 新增测试全部通过

- [ ] **步骤 4：Commit（如有 lint 自动修复）**

```bash
git add -A
git commit -m "chore(ablation): lint and test verification after all fixes"
```

---

## 不修改的文件

| 文件 | 原因 |
|------|------|
| `types.py` | 类型定义无需变更（`round_index` 已有默认值 0） |
| `report.py` | 其仅遍历 metrics dict，key rename 后自动适配 |
| `safety_group.py` | 仅加 `checkpoint_path` 传参 |
| `architecture_group.py` | 仅加 `checkpoint_path` 传参 |
| `metrics.py` | 无变更 |
| `scenario_synthesizer.py` 中 `_build_dimension_combinations` 等纯数据函数 | 无变更 |
