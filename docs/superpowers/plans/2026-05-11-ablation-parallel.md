# 消融实验并行化 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 消融实验三组全局共享状态（bool flag + env var）改为 `contextvars.ContextVar`，`run_batch` 和 Judge 评分改为 `asyncio.gather` 并发，全流程 2.5h → ~18 min。

**架构：** 三处全局状态→ContextVar（任务级隔离，自动 GC）。`run_batch` 加 Semaphore 节流 LLM 并发 + asyncio.Lock 保护 checkpoint 写入。Judge 评分同。

**技术栈：** Python 3.14, contextvars, asyncio, aiofiles

---

## 文件结构

| 文件 | 职责 | 改动类型 |
|------|------|---------|
| `app/agents/rules.py` | `_ablation_disable_rules` 改为 ContextVar | 修改 |
| `app/agents/workflow.py` | `_ablation_disable_feedback` 改为 ContextVar | 修改 |
| `app/agents/probabilistic.py` | `is_enabled()` 从 env var 改为 ContextVar，新增 `set_probabilistic_enabled()` | 修改 |
| `experiments/ablation/ablation_runner.py` | 删 `_set_env/_restore_env`；`run_variant` 接受 `user_id` 参数；`run_batch` 并发 | 修改 |
| `experiments/ablation/safety_group.py` | Judge 评分 `asyncio.gather` | 修改 |
| `experiments/ablation/architecture_group.py` | Judge 评分 `asyncio.gather` | 修改 |

无新建文件。需要修改的现有测试：无（现有 test 应全部通过，ContextVar 默认值与旧行为一致且实验不在 CI 中跑）。

---

### 任务 1：rules.py — `_ablation_disable_rules` 改为 ContextVar

**文件：**
- 修改：`app/agents/rules.py`（约 10 行）

- [ ] **步骤 1：替换声明**

当前：
```python
_ablation_disable_rules: bool = bool(int(os.getenv("ABLATION_DISABLE_RULES", "0")))
```

改为：
```python
import contextvars

_ablation_disable_rules: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_ablation_disable_rules", default=False
)
```

- [ ] **步骤 2：更新 `postprocess_decision` 中的检查**

当前：
```python
if _ablation_disable_rules:
    return decision, []
```

改为：
```python
if _ablation_disable_rules.get():
    return decision, []
```

- [ ] **步骤 3：更新 `set_ablation_disable_rules`**

当前：
```python
def set_ablation_disable_rules(v: bool) -> None:
    global _ablation_disable_rules
    _ablation_disable_rules = v
```

改为：
```python
def set_ablation_disable_rules(v: bool) -> None:
    _ablation_disable_rules.set(v)
```

- [ ] **步骤 4：验证**

运行：`uv run pytest tests/test_rules.py -v`
预期：全部通过

- [ ] **步骤 5：Commit**

```bash
git add app/agents/rules.py
git commit -m "refactor(rules): _ablation_disable_rules bool → ContextVar"
```

---

### 任务 2：workflow.py — `_ablation_disable_feedback` 改为 ContextVar

**文件：**
- 修改：`app/agents/workflow.py`（约 10 行）

- [ ] **步骤 1：替换声明**

当前：
```python
_ablation_disable_feedback: bool = bool(
    int(os.getenv("ABLATION_DISABLE_FEEDBACK", "0"))
)
```

改为：
```python
import contextvars

_ablation_disable_feedback: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_ablation_disable_feedback", default=False
)
```

- [ ] **步骤 2：更新 `_strategy_node` 中的检查**

当前：
```python
if _ablation_disable_feedback:
    weights = { ... }
```

改为：
```python
if _ablation_disable_feedback.get():
    weights = { ... }
```

- [ ] **步骤 3：更新 `set_ablation_disable_feedback`**

当前：
```python
def set_ablation_disable_feedback(v: bool) -> None:
    global _ablation_disable_feedback
    _ablation_disable_feedback = v
```

改为：
```python
def set_ablation_disable_feedback(v: bool) -> None:
    _ablation_disable_feedback.set(v)
```

- [ ] **步骤 4：验证**

运行：`uv run pytest tests/ -v -x`
预期：全部通过，无回归

- [ ] **步骤 5：Commit**

```bash
git add app/agents/workflow.py
git commit -m "refactor(workflow): _ablation_disable_feedback bool → ContextVar"
```

---

### 任务 3：probabilistic.py — is_enabled 改为 ContextVar

**文件：**
- 修改：`app/agents/probabilistic.py`（约 10 行）

- [ ] **步骤 1：新增 ContextVar + setter**

在 `app/agents/probabilistic.py` 的导入区后添加：

```python
import contextvars
import os

_probabilistic_enabled: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_probabilistic_enabled",
    default=os.getenv("PROBABILISTIC_INFERENCE_ENABLED", "1") == "1",
)


def set_probabilistic_enabled(v: bool) -> None:
    """消融实验用：在当前 task 的 Context 中设值。"""
    _probabilistic_enabled.set(v)
```

- [ ] **步骤 2：更新 `is_enabled()`**

当前：
```python
def is_enabled() -> bool:
    return os.getenv("PROBABILISTIC_INFERENCE_ENABLED", "1") == "1"
```

改为：
```python
def is_enabled() -> bool:
    return _probabilistic_enabled.get()
```

- [ ] **步骤 3：验证**

运行：`uv run pytest tests/test_probabilistic.py -v`
预期：全部通过

- [ ] **步骤 4：Commit**

```bash
git add app/agents/probabilistic.py
git commit -m "refactor(probabilistic): is_enabled() env var → ContextVar"
```

---

### 任务 4：ablation_runner.py — 并发化核心重构

**文件：**
- 修改：`experiments/ablation/ablation_runner.py`

- [ ] **步骤 1：run_variant 接受 user_id，删 env 覆盖**

当前 `run_variant` 用 `self._set_env` 控制概率推断开关。改为 `set_probabilistic_enabled()`：

```python
def __init__(self, base_user_id: str = "ablation") -> None:
    """初始化运行器。base_user_id 用作变体 uid 前缀，每组不同（experiment-safety / experiment-arch / experiment-personalization）。"""
    self.base_user_id = base_user_id

async def run_variant(
    self, scenario: Scenario, variant: Variant,
    user_id: str | None = None,
) -> VariantResult:
    """运行单个变体实验。user_id 传 None 则回退 base_user_id。"""
    uid = user_id or self.base_user_id
    t0 = time.perf_counter()

    if variant == Variant.NO_RULES:
        set_ablation_disable_rules(True)
    elif variant == Variant.NO_PROB:
        set_probabilistic_enabled(False)
    elif variant == Variant.NO_FEEDBACK:
        set_ablation_disable_feedback(True)

    if variant == Variant.SINGLE_LLM:
        return await self._run_single_llm(scenario, uid, t0)
    return await self._run_agent_workflow(scenario, variant, uid, t0)
```

注意：无 `try/finally`——ContextVar 随任务自动 GC。无 `_set_env`/`_restore_env` 调用——已删。

- [ ] **步骤 2：`_run_agent_workflow` 接受 `user_id`**

当前签名：`async def _run_agent_workflow(self, scenario: Scenario, variant: Variant, t0: float)`
改为：`async def _run_agent_workflow(self, scenario: Scenario, variant: Variant, user_id: str, t0: float)`

方法体内，所有 `current_user=self.user_id` 改为 `current_user=user_id`。

当前：
```python
workflow = AgentWorkflow(
    data_dir=DATA_DIR,
    memory_mode=MemoryMode.MEMORY_BANK,
    memory_module=mm,
    current_user=self.user_id,
)
```

改为：
```python
workflow = AgentWorkflow(
    data_dir=DATA_DIR,
    memory_mode=MemoryMode.MEMORY_BANK,
    memory_module=mm,
    current_user=user_id,
)
```

- [ ] **步骤 3：`_run_single_llm` 接受 `user_id`**

当前签名：`async def _run_single_llm(self, scenario: Scenario, t0: float)`
改为：`async def _run_single_llm(self, scenario: Scenario, user_id: str, t0: float)`

方法体无需改——SINGLE_LLM 不写 MemoryBank，`user_id` 仅保持签名一致。

- [ ] **步骤 4：重写 `run_batch` 为并发**

```python
async def run_batch(
    self,
    scenarios: list[Scenario],
    variants: list[Variant],
    *,
    concurrency: int = 4,
    checkpoint_path: Path | None = None,
) -> list[VariantResult]:
    """批量运行场景×变体笛卡尔积（并发）。

    concurrency 控制 LLM 并发度（默认 4，匹配 provider concurrency）。
    每变体独立 user_id（{base_user_id}-{scenario.id}-{variant.value}），MemoryBank 无竞态。
    """
    results: list[VariantResult] = []
    existing_ids: set[tuple[str, str]] = set()
    if checkpoint_path:
        existing_ids, existing_results = await _load_checkpoint(checkpoint_path)
        results.extend(existing_results)

    pending = [
        (s, v) for s in scenarios for v in variants
        if (s.id, v.value) not in existing_ids
    ]

    sem = asyncio.Semaphore(concurrency)
    ckpt_lock = asyncio.Lock()

    async def run_one(scenario: Scenario, variant: Variant) -> VariantResult:
        async with sem:
            uid = f"{self.base_user_id}-{scenario.id}-{variant.value}"
            vr = await self.run_variant(scenario, variant, user_id=uid)
            if checkpoint_path:
                async with ckpt_lock:
                    await _append_checkpoint(
                        checkpoint_path, vr, include_modifications=True,
                    )
            return vr

    tasks = [asyncio.create_task(run_one(s, v)) for s, v in pending]
    new_results = await asyncio.gather(*tasks)
    return results + list(new_results)
```

- [ ] **步骤 5：删掉 `_set_env` / `_restore_env`**

完整删除 `_set_env`、`_restore_env` 方法和 `self._original_env` 字段。

- [ ] **步骤 6：验证**

运行：`uv run ruff check experiments/ablation/` 和 `uv run ty check experiments/ablation/`
预期：全部通过

运行：`uv run pytest tests/ -v -x`
预期：全部通过

- [ ] **步骤 7：Commit**

```bash
git add experiments/ablation/ablation_runner.py
git commit -m "perf(ablation): concurrent run_batch via asyncio.gather + ContextVar isolation"
```

---

### 任务 5：safety_group.py — 并发 Judge 评分

**文件：**
- 修改：`experiments/ablation/safety_group.py`

- [ ] **步骤 1：评分改为 `asyncio.gather`**

当前：
```python
scores: list[JudgeScores] = []
for scenario in safety_scenarios:
    scenario_results = [r for r in results if r.scenario_id == scenario.id]
    batch_scores = await judge.score_batch(scenario, scenario_results)
    scores.extend(batch_scores)
```

改为：
```python
async def score_one(scenario: Scenario) -> list[JudgeScores]:
    vrs = [r for r in results if r.scenario_id == scenario.id]
    return await judge.score_batch(scenario, vrs)

tasks = [score_one(s) for s in safety_scenarios]
scores_batches = await asyncio.gather(*tasks)
scores = [s for batch in scores_batches for s in batch]
```

- [ ] **步骤 2：验证**

运行：`uv run pytest tests/experiments/ -v`
预期：全部通过

- [ ] **步骤 3：Commit**

```bash
git add experiments/ablation/safety_group.py
git commit -m "perf(ablation): concurrent judge scoring in safety group"
```

---

### 任务 6：architecture_group.py — 并发 Judge 评分

**文件：**
- 修改：`experiments/ablation/architecture_group.py`

- [ ] **步骤 1：评分改为 `asyncio.gather`**

与任务 5 相同改动——将串行 `for scenario in arch_scenarios: ... judge.score_batch(...)` 替换为 `asyncio.gather`。

- [ ] **步骤 2：验证**

运行：`uv run pytest tests/experiments/ -v`
预期：全部通过

- [ ] **步骤 3：Commit**

```bash
git add experiments/ablation/architecture_group.py
git commit -m "perf(ablation): concurrent judge scoring in architecture group"
```

---

### 任务 7：cli.py main() — 组间并发

**文件：**
- 修改：`experiments/ablation/cli.py`

- [ ] **步骤 1：`main()` 中组间并发调度**

当前 `main()` 串行跑三组。个性化组权重更新有状态，不参与组间并发。

```python
# 在 main() 中替换串行 for 循环
all_group_results: dict[str, GroupResult] = {}

concurrent_groups = [g for g in groups_to_run if g != "personalization"]
serial_group = "personalization" if "personalization" in groups_to_run else None

async def run_one(group: str) -> tuple[str, GroupResult]:
    if group == "safety":
        print(f"\n=== 运行 {group} 组 ===\n")
        result = await _run_safety_experiment(data_dir, all_scenarios, args.seed)
        print(f"安全性组完成: {len(result.variant_results)} 结果")
        return group, result
    if group == "architecture":
        print(f"\n=== 运行 {group} 组 ===\n")
        result = await _run_architecture_experiment(data_dir, all_scenarios, args.seed)
        print(f"架构组完成: {len(result.variant_results)} 结果")
        return group, result
    msg = f"未知组: {group}"
    raise ValueError(msg)

if concurrent_groups:
    tasks = [asyncio.create_task(run_one(g)) for g in concurrent_groups]
    for group, result in await asyncio.gather(*tasks):
        all_group_results[group] = result

if serial_group:
    group = serial_group
    print(f"\n=== 运行 {group} 组 ===\n")
    result = await _run_personalization_experiment(data_dir, all_scenarios, args.seed)
    all_group_results[group] = result
    print(f"个性化组完成: {len(result.variant_results)} 结果")

render_report(all_group_results, results_dir)
```

- [ ] **步骤 2：验证**

运行：`uv run ruff check experiments/ablation/cli.py`
预期：通过

运行：`uv run pytest tests/experiments/ -v`
预期：全部通过

- [ ] **步骤 3：Commit**

```bash
git add experiments/ablation/cli.py
git commit -m "perf(ablation): concurrent inter-group experiment execution"
```

---

### 任务 8：cli.py `_judge_only` — 并发评分

**文件：**
- 修改：`experiments/ablation/cli.py`

- [ ] **步骤 1：`_judge_only` 的评分循环改为并发**

当前 `_judge_only` 按组评分时，`_score_group` 内串联 `for sid, vrs in scenarios_for_results.items()`。改为 `asyncio.gather` 并发评分各场景：

```python
async def _score_group(
    judge: Judge,
    scenarios_for_results: dict[str, list[VariantResult]],
    scenario_by_id: dict[str, Scenario],
) -> list[JudgeScores]:
    """对一组结果的各场景并发评分并汇总。"""
    async def score_one(sid: str, vrs: list[VariantResult]) -> list[JudgeScores]:
        scenario = scenario_by_id.get(sid)
        if scenario is None:
            return []
        return await judge.score_batch(scenario, vrs)

    tasks = [score_one(sid, vrs) for sid, vrs in scenarios_for_results.items()]
    batches = await asyncio.gather(*tasks)
    return [s for batch in batches for s in batch]
```

- [ ] **步骤 2：验证**

运行：`uv run ruff check experiments/ablation/cli.py`
预期：通过

运行：`uv run pytest tests/experiments/ -v`
预期：全部通过

- [ ] **步骤 3：Commit**

```bash
git add experiments/ablation/cli.py
git commit -m "perf(ablation): concurrent judge-only scoring"
```

---

### 任务 9：完整回归验证

- [ ] **步骤 1：全量验证**

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check .
uv run pytest -v -x
```

预期：ruff/ty/pytest 全部通过

- [ ] **步骤 2：最终 Commit（如无则跳过——前面已逐任务 commit，无额外变更即不提交）**

```bash
git commit -m "chore: clean up after ablation parallel implementation" || true
```
