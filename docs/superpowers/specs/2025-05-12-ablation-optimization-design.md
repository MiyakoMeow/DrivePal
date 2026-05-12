# 消融实验框架优化设计

日期：2025-05-12
分支：`refactor/optimize-ablation`

## 目标

优化 `experiments/ablation/` 模块的工程质量、运行时性能和实验方法论。

约束：实验设计不变（三组、变体、指标定义、CLI 参数、输出文件结构）。

## 痛点清单

| # | 类别 | 痛点 |
|---|------|------|
| 1 | 工程 | `personalization_group.py` 541 行，职责过多 |
| 2 | 工程 | 三组编排模式重复（filter → run → score → dump → metrics） |
| 3 | 工程 | I/O 逻辑分散（`_append_checkpoint` 在 runner 中而非 `_io`） |
| 4 | 方法 | Judge 评分固定 3 次，无不一致性检测 |
| 5 | 方法 | `wilcoxon_test` 按 scenario_id 取 `[0]`，不支持多轮配对 |
| 6 | 方法 | `run_batch` 部分失败时无 expected/actual 计数 |
| 7 | 方法 | 场景 ID 语义需文档澄清 |
| 8 | 方法 | 反馈模拟缺少诊断日志 |
| 9 | 性能 | `--judge-only` 不复用已有 scores.json |
| 10 | 性能 | 并发策略对 personalization 组无效（已串行，但 concurrency 参数仍可配） |

## 设计

### §1 公共编排协议

提取 safety 和 architecture 组共享的编排骨架为 `protocol.py`。

**新增文件**：`experiments/ablation/protocol.py`

```python
@dataclass
class GroupConfig:
    group_name: str
    variants: list[Variant]
    scenario_filter: Callable[[Scenario], bool]
    metrics_computer: Callable[..., dict]
    post_hook: Callable[[GroupResult, Judge, list[Scenario]], Awaitable[GroupResult]] | None = None

async def run_group(
    runner: AblationRunner,
    judge: Judge,
    scenarios: list[Scenario],
    config: GroupConfig,
    output_path: Path,
) -> GroupResult:
    """通用实验编排。"""
    filtered = [s for s in scenarios if config.scenario_filter(s)]
    results = await runner.run_batch(filtered, config.variants, checkpoint_path=output_path)
    scores = await _score_scenarios_concurrent(judge, filtered, results)
    await dump_variant_results_jsonl(output_path, results, include_modifications=True)
    metrics = config.metrics_computer(scores, results)
    group_result = GroupResult(group=config.group_name, variant_results=results, judge_scores=scores, metrics=metrics)
    if config.post_hook:
        group_result = await config.post_hook(group_result, judge, filtered)
    return group_result
```

- `_score_scenarios_concurrent`：提取自 safety/architecture 中重复的 `score_one` + `asyncio.gather`。
- `post_hook`：architecture 用它追加 `stage_scores` 聚合。

**影响**：
- `safety_group.py`：删除 `run_safety_group` 编排代码，保留 `compute_safety_metrics`、`safety_stratum`、`SAFETY_COMPLIANCE_THRESHOLD`。
- `architecture_group.py`：删除 `run_architecture_group` 编排代码，保留 `compute_quality_metrics`、`_aggregate_full_stage_scores`、`arch_stratum`、`is_arch_scenario`。
- `cli.py`：`_run_safety_experiment` / `_run_architecture_experiment` 改为调用 `run_group`。
- `personalization_group.py`：不走 `run_group`（串行 + 反馈状态依赖），保留独立编排。

### §2 拆分 personalization_group.py

拆为三个文件：

| 文件 | 职责 | 预估行数 |
|------|------|---------|
| `personalization_group.py` | 实验编排（`run_personalization_group`、`STAGES`、`_build_stages`、`pers_stratum`） | ~180 |
| `feedback_simulator.py` | 反馈模拟 + 权重管理（`simulate_feedback`、`_has_visual_content`、`_extract_task_type`、`update_feedback_weight`、`_read_weights`） | ~150 |
| `preference_metrics.py` | 四个指标计算（`compute_preference_metrics` 及四个私有计算函数） | ~200 |

导入关系：
- `personalization_group.py` → `feedback_simulator`、`preference_metrics`
- `feedback_simulator.py` → `app.memory.*`、`app.storage.*`
- `preference_metrics.py` → `.types`（纯计算）
- `cli.py` 的 `_judge_only` 路径从 `preference_metrics` 和 `personalization_group` 导入

### §3 统一 I/O 层

将 checkpoint 相关函数从 `ablation_runner.py` 移入 `_io.py`：

| 函数 | 当前位置 | 目标位置 |
|------|---------|---------|
| `_load_checkpoint` | `ablation_runner.py` | `_io.py`（公开为 `load_checkpoint`） |
| `_append_checkpoint` | `ablation_runner.py` | `_io.py`（公开为 `append_checkpoint`） |

变更后 `ablation_runner.py` 仅含 `AblationRunner` 类和 `_VARIANT_TIMEOUT_SECONDS` 常量。从 `_io` 导入 checkpoint 函数。

### §4 方法层修复

#### 4a. Judge 评分

保持固定 3 次取中位数，不做自适应。保证实验可复现性和方法论一致性。

#### 4b. 统计方法修复

**wilcoxon_test 多轮支持**：增加 `key_fn` 参数：

```python
def wilcoxon_test(
    scores: list[JudgeScores],
    baseline: str = "full",
    key_fn: Callable[[JudgeScores], str] = lambda s: s.scenario_id,
) -> dict[str, dict]:
```

默认行为不变（按 scenario_id）。personalization 组可传入复合键：

```python
key_fn=lambda s: f"{s.scenario_id}:{s.round_index}"
```

**expected/actual 计数**：`AblationRunner.run_batch` 返回改为 `BatchResult`：

```python
@dataclass
class BatchResult:
    results: list[VariantResult]
    expected: int    # len(scenarios) * len(variants)
    actual: int      # 成功数
    failures: int    # 失败数
```

`GroupResult` 新增 `batch_stats: dict` 字段（`{"expected": N, "actual": M, "failures": F}`）。`_print_step_summary` 输出失败数（若有）。

向后兼容：`run_group` 从 `BatchResult` 中提取 `results` 构造 `GroupResult`。

#### 4c. 场景 ID 语义

在 `scenario_synthesizer.py` 的 `_synthesize_one` 中加注释：

```python
# dim_id 由维度组合唯一决定（360 种排列），
# 同一 dim_id 只会生成一次场景（幂等跳过），不存在同一 ID 对应不同内容的情况。
```

#### 4d. 反馈模拟诊断

在 `feedback_simulator.py` 的 `simulate_feedback` 中，`visual-detail` 阶段加诊断：

```python
if stage == "visual-detail":
    if stages and stages.get("decision") == decision:
        logger.debug("规则引擎未修改 decision，反馈基于原始 LLM 输出 (scenario: %s)", ...)
    return "accept" if _has_visual_content(decision, stages=stages) else "ignore"
```

### §5 性能层

#### 5a. 并发策略

safety/architecture 组的实验运行和 Judge 评分并发度不变。personalization 组串行不变。

#### 5b. 场景加载

不改（360 行同步读 <1ms）。

#### 5c. Judge-only 去重

`--judge-only` 模式先尝试复用已有 `scores.json`：

```python
async def _try_load_existing_scores(
    scores_path: Path,
    variant_results: list[VariantResult],
) -> list[JudgeScores] | None:
    """若 scores.json 存在且完整覆盖 variant_results，返回加载结果；否则返回 None。"""
    if not scores_path.exists():
        return None
    async with aiofiles.open(scores_path, encoding="utf-8") as f:
        raw = await f.read()
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return None
    loaded = [JudgeScores(**s) for s in data.get("scores", [])]
    loaded_keys = {(s.scenario_id, s.variant) for s in loaded}
    required_keys = {(r.scenario_id, r.variant) for r in variant_results}
    return loaded if required_keys <= loaded_keys else None
```

`_judge_only` 中每组先调用 `_try_load_existing_scores`，命中则跳过评分，否则重新评分并覆写。

## 文件变更汇总

| 操作 | 文件 | 说明 |
|------|------|------|
| 新增 | `protocol.py` | 公共编排协议 |
| 新增 | `feedback_simulator.py` | 反馈模拟 + 权重管理 |
| 新增 | `preference_metrics.py` | 偏好指标计算 |
| 修改 | `_io.py` | 接收 checkpoint 函数 |
| 修改 | `ablation_runner.py` | 移除 I/O 函数，`run_batch` 返回 `BatchResult` |
| 修改 | `safety_group.py` | 删除编排代码，仅保留 filter/metrics/config |
| 修改 | `architecture_group.py` | 删除编排代码，仅保留 filter/metrics/config + post_hook |
| 修改 | `personalization_group.py` | 移除反馈模拟和指标计算，仅保留编排 |
| 不变 | `judge.py` | 无变更 |
| 修改 | `metrics.py` | `wilcoxon_test` 增加 `key_fn` 参数 |
| 修改 | `scenario_synthesizer.py` | 加注释 |
| 修改 | `cli.py` | 适配新 API，judge-only 去重 |
| 修改 | `types.py` | 新增 `BatchResult`，`GroupResult` 新增 `batch_stats` |
| 不变 | `report.py` | 无变更 |

## 已决问题

1. **`BatchResult` vs 直接加字段** → 选方案 A：`BatchResult` dataclass。理由：`run_batch` 的调用方不只是 `run_group`（personalization 直接调用），返回类型应明确区分"批量运行结果"和"一组实验结果"。
2. **`wilcoxon_test` 的 `key_fn` 透传** → 不透传至 `compute_comparison`。`compute_comparison` 内部调用 `wilcoxon_test` 时固定用 `scenario_id`（默认值）。personalization 组若需按复合键做 Wilcoxon，直接调用 `wilcoxon_test(scores, key_fn=...)` 而非通过 `compute_comparison`。
