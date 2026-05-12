# 消融实验框架优化 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 重构 `experiments/ablation/` 模块——消除三组编排重复、拆分过大的 personalization 模块、统一 I/O 层、修复统计方法缺陷、添加 judge-only 缓存。

**架构：** 提取公共编排协议 `protocol.py`，safety/architecture 两组共享；personalization 保留独立编排但拆分为三个文件（编排 + 反馈模拟 + 指标计算）；checkpoint I/O 收归 `_io.py`；`run_batch` 返回 `BatchResult` 记录失败计数。

**技术栈：** Python 3.14, pytest (asyncio_mode=auto), ruff, ty

---

## 文件结构

| 文件 | 职责 | 操作 |
|------|------|------|
| `experiments/ablation/types.py` | 数据类型定义（新增 `BatchResult`，`GroupResult` 新增 `batch_stats`） | 修改 |
| `experiments/ablation/_io.py` | 统一 I/O（接收 checkpoint 函数） | 修改 |
| `experiments/ablation/ablation_runner.py` | 变体执行器（使用 `BatchResult`，移除 I/O 函数） | 修改 |
| `experiments/ablation/metrics.py` | 统计指标（`wilcoxon_test` 增加 `key_fn`） | 修改 |
| `experiments/ablation/preference_metrics.py` | 偏好指标计算（从 personalization 提取） | 新增 |
| `experiments/ablation/feedback_simulator.py` | 反馈模拟 + 权重管理（从 personalization 提取） | 新增 |
| `experiments/ablation/personalization_group.py` | 个性化组编排（精简，导入上述两个新模块） | 修改 |
| `experiments/ablation/protocol.py` | 公共编排协议（`GroupConfig` + `run_group`） | 新增 |
| `experiments/ablation/safety_group.py` | 安全组（删除编排代码，仅保留 filter/metrics/config） | 修改 |
| `experiments/ablation/architecture_group.py` | 架构组（删除编排代码，仅保留 filter/metrics/config） | 修改 |
| `experiments/ablation/scenario_synthesizer.py` | 场景合成器（加注释） | 修改 |
| `experiments/ablation/cli.py` | CLI 入口（适配新 API，judge-only 缓存） | 修改 |
| `tests/experiments/test_types.py` | 类型测试 | 修改 |
| `tests/experiments/test_io.py` | I/O 测试（新增 checkpoint 测试） | 修改 |
| `tests/experiments/test_metrics.py` | 指标测试（新增 key_fn 测试） | 修改 |
| `tests/experiments/test_personalization.py` | 个性化测试（适配新导入路径） | 修改 |
| `tests/experiments/test_ablation_optimization.py` | 综合测试（新增 protocol 测试） | 修改 |
| `tests/experiments/test_protocol.py` | 协议测试 | 新增 |

---

### 任务 1：types.py — BatchResult + GroupResult.batch_stats

**文件：**
- 修改：`experiments/ablation/types.py`
- 修改：`tests/experiments/test_types.py`

- [ ] **步骤 1：编写 BatchResult 测试**

在 `tests/experiments/test_types.py` 末尾追加：

```python
from experiments.ablation.types import BatchResult, GroupResult, Variant, VariantResult


class TestBatchResult:
    """批量运行结果."""

    def test_construction_with_defaults(self):
        """给定结果列表，当构造 BatchResult，则 failures 为 expected - actual."""
        results = [
            VariantResult("s1", Variant.FULL, {}, "", None, {}, 100),
            VariantResult("s2", Variant.FULL, {}, "", None, {}, 200),
        ]
        batch = BatchResult(results=results, expected=3)
        assert batch.actual == 2
        assert batch.failures == 1

    def test_all_succeeded(self):
        """给定 expected == actual，当构造 BatchResult，则 failures 为 0."""
        results = [
            VariantResult("s1", Variant.FULL, {}, "", None, {}, 100),
        ]
        batch = BatchResult(results=results, expected=1)
        assert batch.failures == 0


class TestGroupResultBatchStats:
    """GroupResult.batch_stats 字段."""

    def test_default_batch_stats_is_empty(self):
        """给定无 batch_stats，当构造 GroupResult，则 batch_stats 为空字典."""
        gr = GroupResult(
            group="test",
            variant_results=[],
            judge_scores=[],
            metrics={},
        )
        assert gr.batch_stats == {}
```

- [ ] **步骤 2：运行测试验证失败**

```bash
cd /home/miyakomeow/Codes/DrivePal/.worktrees/optimize-ablation
uv run pytest tests/experiments/test_types.py -v
```

预期：FAIL，`cannot import name 'BatchResult'`

- [ ] **步骤 3：实现 BatchResult + GroupResult.batch_stats**

在 `experiments/ablation/types.py` 中：

1. 在 `VariantResult` 后新增 `BatchResult` dataclass：

```python
@dataclass
class BatchResult:
    """批量运行结果——含成功/失败计数."""

    results: list[VariantResult]
    expected: int
    actual: int = 0
    failures: int = 0

    def __post_init__(self) -> None:
        self.actual = len(self.results)
        self.failures = self.expected - self.actual
```

2. `GroupResult` 新增字段 `batch_stats: dict = field(default_factory=dict)`

- [ ] **步骤 4：运行测试验证通过**

```bash
uv run pytest tests/experiments/test_types.py -v
```

- [ ] **步骤 5：运行全量测试确认无回归**

```bash
uv run pytest tests/experiments/ -v
```

- [ ] **步骤 6：Lint + type check**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```

- [ ] **步骤 7：Commit**

```bash
git add experiments/ablation/types.py tests/experiments/test_types.py
git commit -m "feat(ablation): add BatchResult dataclass and GroupResult.batch_stats"
```

---

### 任务 2：_io.py — 接收 checkpoint 函数

**文件：**
- 修改：`experiments/ablation/_io.py`
- 修改：`experiments/ablation/ablation_runner.py`
- 修改：`tests/experiments/test_io.py`

- [ ] **步骤 1：编写 checkpoint I/O 测试**

在 `tests/experiments/test_io.py` 末尾追加：

```python
from experiments.ablation._io import append_checkpoint, load_checkpoint
from experiments.ablation.types import Variant, VariantResult


async def test_append_and_load_checkpoint_roundtrip(tmp_path: Path):
    """给定写入 checkpoint 的 VariantResult，当 load，则应还原完整数据."""
    vr = VariantResult(
        scenario_id="s1",
        variant=Variant.NO_RULES,
        decision={"should_remind": False},
        result_text="test",
        event_id="evt1",
        stages={"decision": {"a": 1}},
        latency_ms=123.4,
        modifications=["mod1"],
        round_index=3,
    )
    path = tmp_path / "checkpoint.jsonl"
    await append_checkpoint(path, vr, include_modifications=True)

    ids, results = await load_checkpoint(path)
    assert ("s1", "no-rules") in ids
    assert len(results) == 1
    assert results[0].scenario_id == "s1"
    assert results[0].variant == Variant.NO_RULES
    assert results[0].modifications == ["mod1"]
    assert results[0].round_index == 3


async def test_load_checkpoint_nonexistent_returns_empty(tmp_path: Path):
    """给定不存在的文件，当 load，则返回空集合和空列表."""
    ids, results = await load_checkpoint(tmp_path / "nope.jsonl")
    assert ids == set()
    assert results == []
```

- [ ] **步骤 2：运行测试验证失败**

```bash
uv run pytest tests/experiments/test_io.py -v
```

预期：FAIL，`cannot import name 'append_checkpoint'`

- [ ] **步骤 3：移动 checkpoint 函数到 _io.py**

1. 将 `ablation_runner.py` 中的 `_load_checkpoint` 移至 `_io.py`，重命名为 `load_checkpoint`（公开），去掉前导下划线。保持函数签名和实现不变，仅改导入来源（`variant_result_from_dict` 已在同文件）。

2. 将 `ablation_runner.py` 中的 `_append_checkpoint` 移至 `_io.py`，重命名为 `append_checkpoint`（公开）。保持实现不变。

3. 在 `ablation_runner.py` 中：
   - 删除 `_load_checkpoint` 和 `_append_checkpoint` 的定义
   - 添加导入：`from ._io import append_checkpoint, load_checkpoint`
   - `run_batch` 中将 `_load_checkpoint(` → `load_checkpoint(`
   - `run_batch` 中将 `_append_checkpoint(` → `append_checkpoint(`

- [ ] **步骤 4：运行测试验证通过**

```bash
uv run pytest tests/experiments/ -v
```

- [ ] **步骤 5：Lint + type check**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```

- [ ] **步骤 6：Commit**

```bash
git add experiments/ablation/_io.py experiments/ablation/ablation_runner.py tests/experiments/test_io.py
git commit -m "refactor(ablation): move checkpoint I/O functions to _io.py"
```

---

### 任务 3：ablation_runner.py — run_batch 返回 BatchResult

**文件：**
- 修改：`experiments/ablation/ablation_runner.py`
- 修改：`experiments/ablation/safety_group.py`（调用方适配）
- 修改：`experiments/ablation/architecture_group.py`（调用方适配）
- 修改：`experiments/ablation/personalization_group.py`（调用方适配）

- [ ] **步骤 1：修改 run_batch 返回 BatchResult**

在 `ablation_runner.py` 中：

1. 添加导入：`from .types import BatchResult, Scenario, Variant, VariantResult`（合并已有导入）
2. 修改 `run_batch` 签名和返回值：

将 `run_batch` 末尾改为：

```python
expected = len(scenarios) * len(variants)
# ... (existing gather logic)
succeeded = [r for r in new_results if isinstance(r, VariantResult)]
failures = [r for r in new_results if isinstance(r, Exception)]
if failures:
    failure_msgs = "; ".join(str(f) for f in failures[:5])
    logger.error(
        "%d/%d variant runs failed: %s",
        len(failures),
        len(new_results),
        failure_msgs,
    )
all_results = results + succeeded
return BatchResult(results=all_results, expected=expected)
```

- [ ] **步骤 2：适配三个调用方**

**safety_group.py** `run_safety_group`：将 `results = await runner.run_batch(...)` 后解包：

```python
batch = await runner.run_batch(safety_scenarios, variants, checkpoint_path=output_path)
results = batch.results
```

所有后续使用 `results` 的代码不变。在构造 `GroupResult` 时传入 `batch_stats`：

```python
return GroupResult(
    group="safety",
    variant_results=batch.results,
    judge_scores=scores,
    metrics=metrics,
    batch_stats={"expected": batch.expected, "actual": batch.actual, "failures": batch.failures},
)
```

**architecture_group.py** `run_architecture_group`：同理解包。

**personalization_group.py**：该模块不使用 `run_batch`（手动逐轮调用 `runner.run_variant`），不受影响。

- [ ] **步骤 3：运行全量测试**

```bash
uv run pytest tests/experiments/ -v
```

- [ ] **步骤 4：Lint + type check**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```

- [ ] **步骤 5：Commit**

```bash
git add experiments/ablation/ablation_runner.py experiments/ablation/safety_group.py experiments/ablation/architecture_group.py
git commit -m "refactor(ablation): run_batch returns BatchResult with failure tracking"
```

---

### 任务 4：metrics.py — wilcoxon_test 增加 key_fn

**文件：**
- 修改：`experiments/ablation/metrics.py`
- 修改：`tests/experiments/test_ablation_optimization.py`

- [ ] **步骤 1：编写 key_fn 测试**

在 `tests/experiments/test_ablation_optimization.py` 的 `TestWilcoxonTest` 类中追加：

```python
def test_custom_key_fn_groups_by_round_index(self):
    """给定自定义 key_fn 按复合键配对，当 wilcoxon_test，则应按复合键分组."""
    scores = []
    for i in range(5):
        scores.append(JudgeScores(f"s{i}", Variant.FULL, 3, 3, 4 + i, [], ""))
        scores.append(JudgeScores(f"s{i}", Variant.NO_RULES, 3, 3, 2, [], ""))
    # key_fn 用 round_index（此处 round_index 固定为 0，全部按 scenario_id 配对）
    result = wilcoxon_test(scores, key_fn=lambda s: s.scenario_id)
    assert "no-rules" in result
    assert result["no-rules"]["n_pairs"] == 5
```

- [ ] **步骤 2：运行测试验证通过（默认行为不变）**

```bash
uv run pytest tests/experiments/test_ablation_optimization.py::TestWilcoxonTest -v
```

默认行为（不传 key_fn）应仍通过。

- [ ] **步骤 3：实现 key_fn 参数**

修改 `metrics.py` 中 `wilcoxon_test` 签名：

```python
from collections.abc import Callable

def wilcoxon_test(
    scores: list[JudgeScores],
    baseline: str = "full",
    *,
    key_fn: Callable[[JudgeScores], str] | None = None,
) -> dict[str, dict]:
```

函数体内，将 `by_pair` 的键改为：

```python
_get_key = key_fn or (lambda s: s.scenario_id)
# ...
by_pair: dict[str, dict[str, list[float]]] = {}
for s in scores:
    by_pair.setdefault(_get_key(s), {}).setdefault(s.variant.value, []).append(
        s.overall_score
    )
```

- [ ] **步骤 4：运行全量测试**

```bash
uv run pytest tests/experiments/ -v
```

- [ ] **步骤 5：Lint + type check**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```

- [ ] **步骤 6：Commit**

```bash
git add experiments/ablation/metrics.py tests/experiments/test_ablation_optimization.py
git commit -m "feat(ablation): add key_fn parameter to wilcoxon_test for multi-round pairing"
```

---

### 任务 5：提取 feedback_simulator.py + 反馈诊断

**必须在任务 6 之前完成——任务 6 的 preference_metrics.py 需从此导入 `_has_visual_content`。**

**文件：**
- 新增：`experiments/ablation/feedback_simulator.py`
- 修改：`experiments/ablation/personalization_group.py`
- 修改：`tests/experiments/test_personalization.py`

- [ ] **步骤 1：创建 feedback_simulator.py**

从 `personalization_group.py` 提取以下内容到新文件 `experiments/ablation/feedback_simulator.py`：

**接口 + 思路**：新文件包含以下从 personalization_group.py 原样搬入的函数和常量：

- 常量：`_SIMULATED_ACCEPT_PROB`、`_KNOWN_TASK_TYPES`
- `simulate_feedback(decision, stage, rng, *, stages=None) -> Literal["accept", "ignore"]`
- `_has_visual_content(decision, *, stages=None) -> bool`
- `_extract_task_type(stages) -> str | None`
- `update_feedback_weight(user_id, event_id, action, *, task_type=None) -> None`
- `_read_weights(user_id) -> dict`

导入：`app.memory.*`、`app.storage.*`、`app.config.user_data_dir`、`logging`。

**新增：反馈诊断日志**。在 `simulate_feedback` 的 `visual-detail` 分支中加诊断：

```python
if stage == "visual-detail":
    if stages and stages.get("decision") == decision:
        logger.debug(
            "规则引擎未修改 decision，反馈基于原始 LLM 输出"
        )
    return "accept" if _has_visual_content(decision, stages=stages) else "ignore"
```

- [ ] **步骤 2：修改 personalization_group.py**

1. 删除所有被提取的函数定义和常量
2. 添加导入：`from .feedback_simulator import simulate_feedback, update_feedback_weight`
3. `run_personalization_group` 中的调用代码不变（函数名相同）

- [ ] **步骤 3：修改测试导入**

`tests/experiments/test_personalization.py` 中：
- `from experiments.ablation.personalization_group import _has_visual_content` 改为 `from experiments.ablation.feedback_simulator import _has_visual_content`

- [ ] **步骤 4：运行全量测试**

```bash
uv run pytest tests/experiments/ -v
```

- [ ] **步骤 5：Lint + type check**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```

- [ ] **步骤 6：Commit**

```bash
git add experiments/ablation/feedback_simulator.py experiments/ablation/personalization_group.py tests/experiments/test_personalization.py
git commit -m "refactor(ablation): extract feedback_simulator.py with diagnostics"
```

---

### 任务 6：提取 preference_metrics.py

**前置依赖：任务 5（`feedback_simulator.py` 已创建，含 `_has_visual_content`）。**

**文件：**
- 新增：`experiments/ablation/preference_metrics.py`
- 修改：`experiments/ablation/personalization_group.py`
- 修改：`tests/experiments/test_personalization.py`
- 修改：`experiments/ablation/cli.py`

此任务从 `personalization_group.py` 提取指标计算函数到独立模块。代码为纯搬运——函数签名和实现不变，仅改变模块位置。

- [ ] **步骤 1：创建 preference_metrics.py**

从 `personalization_group.py` 提取以下内容到新文件 `experiments/ablation/preference_metrics.py`：

**接口 + 思路**：新文件包含以下从 personalization_group.py 原样搬入的函数和常量：

- 常量：`_MIN_HISTORY_LEN`、`_INITIAL_WEIGHT_TOLERANCE`、`_CONVERGENCE_TOLERANCE`、`_CONSECUTIVE_FOR_CONVERGENCE`
- `compute_preference_metrics(results, weight_history, stages, *, scores=None) -> dict`
- `_compute_matching_rate(results, weight_history) -> dict[str, float]`
- `_decision_matches_stage(decision, stage) -> bool | None`
- `_compute_convergence_speed(weight_history) -> float`
- `_compute_stability(weight_history, stages) -> float`
- `_compute_decision_divergence(results, weight_history) -> float`

导入：
- `from .types import JudgeScores, Variant, VariantResult`
- `from .judge import detect_judge_degradation`
- `from .feedback_simulator import _has_visual_content`（`_decision_matches_stage` 依赖此函数）

- [ ] **步骤 2：修改 personalization_group.py**

1. 删除所有被提取的函数定义和常量
2. 添加导入：`from .preference_metrics import compute_preference_metrics`
3. `run_personalization_group` 中调用 `compute_preference_metrics(...)` 的代码不变（函数名和签名相同）

- [ ] **步骤 3：修改 cli.py 导入**

`cli.py` 中 `from .personalization_group import compute_preference_metrics, _build_stages` 改为：

```python
from .personalization_group import _build_stages
from .preference_metrics import compute_preference_metrics
```

- [ ] **步骤 4：修改测试导入**

`tests/experiments/test_personalization.py` 中：
- `from experiments.ablation.personalization_group import _compute_decision_divergence, _compute_stability` 改为 `from experiments.ablation.preference_metrics import _compute_decision_divergence, _compute_stability`

- [ ] **步骤 5：运行全量测试**

```bash
uv run pytest tests/experiments/ -v
```

- [ ] **步骤 6：Lint + type check**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```

- [ ] **步骤 7：Commit**

```bash
git add experiments/ablation/preference_metrics.py experiments/ablation/personalization_group.py experiments/ablation/cli.py tests/experiments/test_personalization.py
git commit -m "refactor(ablation): extract preference_metrics.py from personalization_group"
```

---

### 任务 7：创建 protocol.py + 重构 safety_group.py

**文件：**
- 新增：`experiments/ablation/protocol.py`
- 修改：`experiments/ablation/safety_group.py`
- 修改：`experiments/ablation/cli.py`
- 新增：`tests/experiments/test_protocol.py`

- [ ] **步骤 1：编写 protocol 测试**

创建 `tests/experiments/test_protocol.py`：

```python
"""测试公共编排协议."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from experiments.ablation.protocol import GroupConfig, run_group
from experiments.ablation.types import (
    BatchResult,
    GroupResult,
    JudgeScores,
    Scenario,
    Variant,
    VariantResult,
)


def _make_scenario(sid: str, safety: bool = True) -> Scenario:
    return Scenario(
        id=sid,
        driving_context={},
        user_query="test",
        expected_decision={},
        expected_task_type="meeting",
        safety_relevant=safety,
        scenario_type="city_driving",
    )


@pytest.fixture()
def mock_runner():
    runner = MagicMock()
    batch = BatchResult(
        results=[
            VariantResult("s1", Variant.FULL, {}, "", None, {}, 100),
            VariantResult("s1", Variant.NO_RULES, {}, "", None, {}, 100),
        ],
        expected=2,
    )
    runner.run_batch = AsyncMock(return_value=batch)
    return runner


@pytest.fixture()
def mock_judge():
    judge = MagicMock()
    judge.score_batch = AsyncMock(
        return_value=[
            JudgeScores("s1", Variant.FULL, 5, 5, 5, [], "ok"),
            JudgeScores("s1", Variant.NO_RULES, 3, 3, 3, [], "ok"),
        ]
    )
    return judge


async def test_run_group_filters_scenarios(mock_runner, mock_judge, tmp_path):
    """给定场景过滤器，当 run_group，则仅传入过滤后的场景."""
    scenarios = [_make_scenario("s1", safety=True), _make_scenario("s2", safety=False)]
    config = GroupConfig(
        group_name="safety",
        variants=[Variant.FULL, Variant.NO_RULES],
        scenario_filter=lambda s: s.safety_relevant,
        metrics_computer=lambda scores, results: {},
    )
    output = tmp_path / "results.jsonl"
    result = await run_group(mock_runner, mock_judge, scenarios, config, output)

    assert result.group == "safety"
    assert result.batch_stats["expected"] == 2
    # run_batch 应只收到 s1（过滤后仅 1 场景 × 2 变体 = 2 expected）
    called_scenarios = mock_runner.run_batch.call_args[0][0]
    assert len(called_scenarios) == 1
    assert called_scenarios[0].id == "s1"


async def test_run_group_with_post_hook(mock_runner, mock_judge, tmp_path):
    """给定 post_hook，当 run_group，则 post_hook 被调用并可修改 GroupResult."""

    async def add_tag(gr: GroupResult, judge, scenarios) -> GroupResult:
        gr.metrics["tagged"] = True
        return gr

    scenarios = [_make_scenario("s1")]
    config = GroupConfig(
        group_name="test",
        variants=[Variant.FULL],
        scenario_filter=lambda s: True,
        metrics_computer=lambda scores, results: {},
        post_hook=add_tag,
    )
    result = await run_group(mock_runner, mock_judge, scenarios, config, tmp_path / "results.jsonl")
    assert result.metrics["tagged"] is True
```

- [ ] **步骤 2：运行测试验证失败**

```bash
uv run pytest tests/experiments/test_protocol.py -v
```

预期：FAIL，`cannot import name 'GroupConfig'`

- [ ] **步骤 3：创建 protocol.py**

创建 `experiments/ablation/protocol.py`：

```python
"""公共实验编排协议."""

import asyncio
import logging
from collections.abc import Callable, Awaitable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ._io import dump_variant_results_jsonl
from .types import BatchResult, GroupResult, JudgeScores, Scenario, VariantResult

if TYPE_CHECKING:
    from .ablation_runner import AblationRunner
    from .judge import Judge

logger = logging.getLogger(__name__)


@dataclass
class GroupConfig:
    """一组实验的声明式配置."""

    group_name: str
    variants: list  # list[Variant]，避免循环导入用 list
    scenario_filter: Callable[[Scenario], bool]
    metrics_computer: Callable[..., dict]
    post_hook: Callable[[GroupResult, object, list[Scenario]], Awaitable[GroupResult]] | None = None


async def run_group(
    runner: AblationRunner,
    judge: Judge,
    scenarios: list[Scenario],
    config: GroupConfig,
    output_path: Path,
) -> GroupResult:
    """通用实验编排：filter → run_batch → score → dump → metrics → post_hook."""
    filtered = [s for s in scenarios if config.scenario_filter(s)]
    batch: BatchResult = await runner.run_batch(
        filtered, config.variants, checkpoint_path=output_path
    )
    scores = await _score_scenarios_concurrent(judge, filtered, batch.results)
    await dump_variant_results_jsonl(output_path, batch.results, include_modifications=True)
    metrics = config.metrics_computer(scores, batch.results)
    group_result = GroupResult(
        group=config.group_name,
        variant_results=batch.results,
        judge_scores=scores,
        metrics=metrics,
        batch_stats={
            "expected": batch.expected,
            "actual": batch.actual,
            "failures": batch.failures,
        },
    )
    if config.post_hook:
        group_result = await config.post_hook(group_result, judge, filtered)
    return group_result


async def _score_scenarios_concurrent(
    judge: Judge,
    scenarios: list[Scenario],
    results: list[VariantResult],
) -> list[JudgeScores]:
    """并发评分所有场景的所有变体."""

    async def score_one(scenario: Scenario) -> list[JudgeScores]:
        vrs = [r for r in results if r.scenario_id == scenario.id]
        return await judge.score_batch(scenario, vrs)

    tasks = [score_one(s) for s in scenarios]
    batches = await asyncio.gather(*tasks, return_exceptions=True)
    scores: list[JudgeScores] = []
    for batch in batches:
        if isinstance(batch, Exception):
            logger.error("Judge scoring failed: %s", batch)
        elif isinstance(batch, list):
            scores.extend(batch)
    return scores
```

- [ ] **步骤 4：运行 protocol 测试验证通过**

```bash
uv run pytest tests/experiments/test_protocol.py -v
```

- [ ] **步骤 5：重构 safety_group.py 使用 protocol**

1. 删除 `run_safety_group` 函数
2. 保留 `compute_safety_metrics`、`safety_stratum`、`SAFETY_COMPLIANCE_THRESHOLD`
3. 新增 `make_safety_config()` 工厂函数：

```python
from .protocol import GroupConfig

def make_safety_config() -> GroupConfig:
    """构造安全性组配置."""
    return GroupConfig(
        group_name="safety",
        variants=[Variant.FULL, Variant.NO_RULES, Variant.NO_PROB],
        scenario_filter=lambda s: s.safety_relevant,
        metrics_computer=compute_safety_metrics,
    )
```

- [ ] **步骤 6：修改 cli.py 的 _run_safety_experiment**

```python
from .protocol import run_group
from .safety_group import make_safety_config

async def _run_safety_experiment(scenarios, run_dir):
    runner = AblationRunner(base_user_id="experiment-safety")
    judge = Judge()
    config = make_safety_config()
    return await run_group(runner, judge, scenarios, config, run_dir / "safety" / "results.jsonl")
```

- [ ] **步骤 7：运行全量测试**

```bash
uv run pytest tests/experiments/ -v
```

- [ ] **步骤 8：Lint + type check**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```

- [ ] **步骤 9：Commit**

```bash
git add experiments/ablation/protocol.py experiments/ablation/safety_group.py experiments/ablation/cli.py tests/experiments/test_protocol.py
git commit -m "refactor(ablation): add protocol.py, refactor safety_group to use it"
```

---

### 任务 8：重构 architecture_group.py 使用 protocol

**文件：**
- 修改：`experiments/ablation/architecture_group.py`
- 修改：`experiments/ablation/cli.py`

- [ ] **步骤 1：重构 architecture_group.py**

1. 删除 `run_architecture_group` 函数
2. 保留 `compute_quality_metrics`、`_aggregate_full_stage_scores`、`arch_stratum`、`is_arch_scenario`
3. 新增 `make_architecture_config()` 工厂函数。architecture 有 post_hook（stage_scores 聚合），需要一个独立的工厂函数：

```python
from .protocol import GroupConfig, run_group

def make_architecture_config() -> GroupConfig:
    """构造架构组配置（含 stage_scores post_hook）."""
    return GroupConfig(
        group_name="architecture",
        variants=[Variant.FULL, Variant.SINGLE_LLM],
        scenario_filter=is_arch_scenario,
        metrics_computer=compute_quality_metrics,
        post_hook=_stage_scores_hook,
    )

async def _stage_scores_hook(
    gr: GroupResult, judge: Judge, scenarios: list[Scenario],
) -> GroupResult:
    """架构组后处理：聚合 Full 变体中间阶段评分."""
    full_results = [r for r in gr.variant_results if r.variant == Variant.FULL]
    gr.metrics["stage_scores"] = await _aggregate_full_stage_scores(judge, full_results)
    return gr
```

- [ ] **步骤 2：修改 cli.py 的 _run_architecture_experiment**

```python
from .architecture_group import make_architecture_config

async def _run_architecture_experiment(scenarios, run_dir):
    runner = AblationRunner(base_user_id="experiment-arch")
    judge = Judge()
    config = make_architecture_config()
    return await run_group(runner, judge, scenarios, config, run_dir / "architecture" / "results.jsonl")
```

- [ ] **步骤 3：运行全量测试**

```bash
uv run pytest tests/experiments/ -v
```

- [ ] **步骤 4：Lint + type check**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```

- [ ] **步骤 5：Commit**

```bash
git add experiments/ablation/architecture_group.py experiments/ablation/cli.py
git commit -m "refactor(ablation): refactor architecture_group to use protocol with post_hook"
```

---

### 任务 9：cli.py — BatchResult 输出 + judge-only 缓存

**文件：**
- 修改：`experiments/ablation/cli.py`
- 修改：`tests/experiments/test_ablation_optimization.py`

- [ ] **步骤 1：修改 _print_step_summary 输出失败数**

在 `cli.py` 的 `_print_step_summary` 中，在 metrics_parts 构建后、degradation 检查前，添加失败数输出：

```python
batch_stats = result.batch_stats
if batch_stats.get("failures", 0) > 0:
    print(f"  ⚠ {batch_stats['failures']} variant runs failed (expected {batch_stats['expected']})")
```

- [ ] **步骤 2：实现 _try_load_existing_scores**

在 `cli.py` 中添加函数：

```python
async def _try_load_existing_scores(
    scores_path: Path,
    variant_results: list[VariantResult],
) -> list[JudgeScores] | None:
    """若 scores.json 存在且完整覆盖 variant_results，返回加载结果；否则返回 None."""
    if not scores_path.exists():
        return None
    try:
        async with aiofiles.open(scores_path, encoding="utf-8") as f:
            raw = await f.read()
        data = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return None
    loaded: list[JudgeScores] = []
    for s in data.get("scores", []):
        loaded.append(JudgeScores(
            scenario_id=s["scenario_id"],
            variant=Variant(s["variant"]),
            safety_score=s["safety_score"],
            reasonableness_score=s["reasonableness_score"],
            overall_score=s["overall_score"],
            violation_flags=s.get("violation_flags", []),
            explanation=s.get("explanation", ""),
        ))
    loaded_keys = {(s.scenario_id, s.variant) for s in loaded}
    required_keys = {(r.scenario_id, r.variant) for r in variant_results}
    return loaded if required_keys <= loaded_keys else None
```

- [ ] **步骤 3：修改 _judge_only 使用缓存**

在 `_judge_only` 的 for 循环中，`variant_results = await _load_variant_results(...)` 后添加：

```python
# 尝试复用已有评分
existing_scores = await _try_load_existing_scores(
    run_dir / group_name / "scores.json", variant_results,
)
if existing_scores is not None:
    scores = existing_scores
    print(f"{group_name} 组复用已有评分: {len(scores)} 条")
else:
    scores = await _score_group(judge, scenarios_for_results, scenario_by_id)
    await write_scores_json(run_dir / group_name / "scores.json", scores)
```

替换原来的 `scores = await _score_group(...)` + `await write_scores_json(...)` 两行。

- [ ] **步骤 4：编写 judge-only 缓存测试**

在 `tests/experiments/test_ablation_optimization.py` 末尾添加：

```python
class TestJudgeOnlyCaching:
    """--judge-only 模式复用已有 scores.json."""

    async def test_try_load_existing_scores_returns_scores_when_complete(self, tmp_path):
        """给定完整 scores.json，当 _try_load_existing_scores，则返回全部评分."""
        from experiments.ablation.cli import _try_load_existing_scores

        scores_data = {
            "scores": [
                {
                    "scenario_id": "s1",
                    "variant": "full",
                    "safety_score": 5,
                    "reasonableness_score": 4,
                    "overall_score": 4,
                    "violation_flags": [],
                    "explanation": "ok",
                },
                {
                    "scenario_id": "s1",
                    "variant": "no-rules",
                    "safety_score": 3,
                    "reasonableness_score": 3,
                    "overall_score": 3,
                    "violation_flags": [],
                    "explanation": "ok",
                },
            ]
        }
        path = tmp_path / "scores.json"
        path.write_text(json.dumps(scores_data))

        variant_results = [
            VariantResult("s1", Variant.FULL, {}, "", None, {}, 100),
            VariantResult("s1", Variant.NO_RULES, {}, "", None, {}, 100),
        ]
        loaded = await _try_load_existing_scores(path, variant_results)
        assert loaded is not None
        assert len(loaded) == 2

    async def test_try_load_existing_scores_returns_none_when_incomplete(self, tmp_path):
        """给定不完整 scores.json，当 _try_load_existing_scores，则返回 None."""
        from experiments.ablation.cli import _try_load_existing_scores

        scores_data = {"scores": [{"scenario_id": "s1", "variant": "full", "safety_score": 5, "reasonableness_score": 4, "overall_score": 4, "violation_flags": [], "explanation": ""}]}
        path = tmp_path / "scores.json"
        path.write_text(json.dumps(scores_data))

        variant_results = [
            VariantResult("s1", Variant.FULL, {}, "", None, {}, 100),
            VariantResult("s1", Variant.NO_RULES, {}, "", None, {}, 100),
        ]
        loaded = await _try_load_existing_scores(path, variant_results)
        assert loaded is None

    async def test_try_load_existing_scores_returns_none_when_missing(self, tmp_path):
        """给定不存在的文件，当 _try_load_existing_scores，则返回 None."""
        from experiments.ablation.cli import _try_load_existing_scores

        loaded = await _try_load_existing_scores(tmp_path / "nope.json", [])
        assert loaded is None
```

- [ ] **步骤 5：运行全量测试**

```bash
uv run pytest tests/experiments/ -v
```

- [ ] **步骤 6：Lint + type check**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```

- [ ] **步骤 7：Commit**

```bash
git add experiments/ablation/cli.py tests/experiments/test_ablation_optimization.py
git commit -m "feat(ablation): add judge-only score caching and failure count output"
```

---

### 任务 10：scenario_synthesizer.py — 注释 + _io.py 注释修复

**文件：**
- 修改：`experiments/ablation/scenario_synthesizer.py`
- 修改：`experiments/ablation/_io.py`

- [ ] **步骤 1：scenario_synthesizer.py 加注释**

在 `_synthesize_one` 函数内 `dim_id = f"...` 行后添加：

```python
# dim_id 由维度组合唯一决定（360 种排列），
# 同一 dim_id 只会生成一次场景（幂等跳过），不存在同一 ID 对应不同内容的情况。
```

- [ ] **步骤 2：_io.py L84 注释修正**

将 `write_summary` 中的注释改为：

```python
"""写 JSON 总结文件。timestamp 始终由系统生成，覆盖 data 中同名键。"""
```

- [ ] **步骤 3：运行全量测试**

```bash
uv run pytest tests/experiments/ -v
```

- [ ] **步骤 4：Commit**

```bash
git add experiments/ablation/scenario_synthesizer.py experiments/ablation/_io.py
git commit -m "docs(ablation): clarify scenario ID semantics and fix _io.py comment"
```

---

### 任务 11：最终验证

- [ ] **步骤 1：全量 lint + type check**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```

- [ ] **步骤 2：全量测试**

```bash
uv run pytest tests/ -v
```

- [ ] **步骤 3：验证 CLI 帮助信息不变**

```bash
uv run python -m experiments.ablation --help
```

确认 `--group`、`--synthesize-only`、`--judge-only`、`--data-dir`、`--seed`、`--run-id` 参数仍存在且含义不变。

- [ ] **步骤 4：最终 commit**

```bash
git add -A
git commit --allow-empty -m "chore: final verification for ablation optimization refactor"
```
