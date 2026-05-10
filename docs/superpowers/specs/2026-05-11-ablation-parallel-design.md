# 消融实验并行化设计

## 问题

消融实验（`python -m experiments.ablation`）全串行执行，2.5h 出结果。LLM 调用是唯一瓶颈，provider 设 `concurrency=4` 却只用 1 个槽位。

## 设计目标

1. **最快执行时间**——充分用满 provider concurrency=4
2. **结果可重现**——种子确定性不变
3. **代码可维护**——contextvars 原地替换，不改调用链

## 变更概要（6 文件，~100 行）

| 文件 | 改动 |
|------|------|
| `app/agents/rules.py` | `_ablation_disable_rules` → `contextvars.ContextVar` |
| `app/agents/workflow.py` | `_ablation_disable_feedback` → `contextvars.ContextVar` |
| `app/agents/probabilistic.py` | `is_enabled()` 从读 env var 改为读 context var |
| `experiments/ablation/ablation_runner.py` | 删 `_set_env/_restore_env`；`run_batch` 改为 `asyncio.gather` + Semaphore；每变体独立 `user_id`；Checkpoint 加锁 |
| `experiments/ablation/safety_group.py` | Judge 评分改为 `asyncio.gather` |
| `experiments/ablation/architecture_group.py` | Judge 评分改为 `asyncio.gather` |

个性化组不参与组内并行（有状态权重更新，20 轮串行即可）。

## 详细设计

### 1. ContextVars——三处全局状态 → 任务隔离

#### `rules.py`

```python
import contextvars

_ablation_disable_rules: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_ablation_disable_rules", default=False
)

def set_ablation_disable_rules(v: bool) -> None:
    _ablation_disable_rules.set(v)
```

`postprocess_decision` 中原 `if _ablation_disable_rules:` 改为 `if _ablation_disable_rules.get():`。

#### `workflow.py`

```python
_ablation_disable_feedback: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_ablation_disable_feedback", default=False
)

def set_ablation_disable_feedback(v: bool) -> None:
    _ablation_disable_feedback.set(v)
```

`_strategy_node` 中原 `if _ablation_disable_feedback:` 改为 `if _ablation_disable_feedback.get():`。

删掉 `os.getenv("ABLATION_DISABLE_FEEDBACK")` 初始值——ablation 实验显式调用 setter，不再靠 env var 初始化。

#### `probabilistic.py`

```python
_probabilistic_enabled: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_probabilistic_enabled",
    default=os.getenv("PROBABILISTIC_INFERENCE_ENABLED", "1") == "1",
)

def set_probabilistic_enabled(v: bool) -> None:
    _probabilistic_enabled.set(v)

def is_enabled() -> bool:
    return _probabilistic_enabled.get()
```

**关键行为**：`asyncio.create_task()` 自动复制当前 `contextvars.Context`。每任务独立副本，设值不影响其他任务。无需 cleanup。

### 2. AblationRunner——并发 run_batch

注意：每组的 `base_user_id` 已不同（safety 组 `AblationRunner(user_id="experiment-safety")`，arch 组 `user_id="experiment-arch"`，personalization 组 `user_id="experiment-personalization"`），生成的完整 uid 不会跨组冲突。

#### 删除 `_set_env` / `_restore_env`

不再需要环境变量覆盖——`set_probabilistic_enabled()` 取代。

#### run_variant

```python
async def run_variant(
    self, scenario: Scenario, variant: Variant,
    user_id: str | None = None,
) -> VariantResult:
    uid = user_id or self.base_user_id
    t0 = time.perf_counter()

    # context var 自动隔离，无需 finally cleanup
    if variant == Variant.NO_RULES:
        set_ablation_disable_rules(True)
    elif variant == Variant.NO_PROB:
        set_probabilistic_enabled(False)
    elif variant == Variant.NO_FEEDBACK:
        set_ablation_disable_feedback(True)

    if variant == Variant.SINGLE_LLM:
        return await self._run_single_llm(scenario, uid)
    return await self._run_agent_workflow(scenario, variant, uid)
```

注意：context var 只在当前任务生效，`finally` 中的还原不再需要——任务结束 Context 自然 GC。

#### run_batch

```python
async def run_batch(
    self, scenarios, variants, *, concurrency: int = 4,
    checkpoint_path=None,
) -> list[VariantResult]:
    results, existing_ids = (
        await _load_checkpoint(checkpoint_path) if checkpoint_path else ([], set())
    )
    pending = [
        (s, v) for s in scenarios for v in variants
        if (s.id, v.value) not in existing_ids
    ]

    sem = asyncio.Semaphore(concurrency)
    ckpt_lock = asyncio.Lock()

    async def run_one(scenario, variant):
        async with sem:
            uid = f"{self.base_user_id}-{scenario.id}-{variant.value}"
            vr = await self.run_variant(scenario, variant, user_id=uid)
            if checkpoint_path:
                async with ckpt_lock:
                    # include_modifications=True 保证 checkpoint 存 modifications
                    # 供续跑加载后 interception_rate 指标计算正确
                    await _append_checkpoint(
                        checkpoint_path, vr, include_modifications=True
                    )
            return vr

    tasks = [asyncio.create_task(run_one(s, v)) for s, v in pending]
    new_results = await asyncio.gather(*tasks)
    return results + list(new_results)
```

关键设计点：

- **每变体独立 `user_id`**：`{base_user_id}-{scenario.id}-{variant.value}`，MemoryBank 各写各的，无竞态
- **asyncio.Semaphore(concurrency)**：控制 LLM 并发度，默认 4（匹配 provider）
- **checkpoint asyncio.Lock**：防止两个协程同时 `f.write()` 交错
- **续跑兼容**：先加载已有结果，再并发跑未完成的

### 3. Judge 评分

`safety_group.py` 和 `architecture_group.py` 中原串行评分改为并发：

```python
async def score_one(scenario):
    vrs = [r for r in results if r.scenario_id == scenario.id]
    return await judge.score_batch(scenario, vrs)

tasks = [score_one(s) for s in scenarios]
scores_batches = await asyncio.gather(*tasks)
scores = [s for batch in scores_batches for s in batch]
```

Judge 内部保持 3 次取中位数不变。Provider 层面的 Semaphore(4) 自然节流。

### 4. 个性化组——特殊处理

不参与组内并行。`personalization_group.py` 保持现有串行逻辑，因为 20 轮权重更新有状态：

```
轮 1 FULL → 写 meeting: 0.6
轮 2 FULL → 读 meeting: 0.6 → 写 0.7
```

`main()` 中三组可走组间并行（asyncio 级别，非 `concurrent.futures`）：

```python
async def main(...):
    tasks = []
    for group in groups_to_run:
        if group == "safety":
            tasks.append(asyncio.create_task(_run_safety_experiment(...)))
        elif group == "architecture":
            tasks.append(asyncio.create_task(_run_architecture_experiment(...)))
        elif group == "personalization":
            # 个性化组串行——权重更新有状态
            pass
    results = await asyncio.gather(*tasks)
```

个性化组串行跑，不影响大局（~18 min）。

### 5. `--judge-only` 适配

`_judge_only` 中评分同样改为并发 `asyncio.gather`。

### 6. 速度估算

| 组 | 串行 | 并行 | 加速比 |
|----|------|------|--------|
| safety | 69 min | ~18 min | 3.8x |
| architecture | 57 min | ~15 min | 3.8x |
| personalization | 18 min | 18 min（串行） | 1x |
| 组间并行 | | ~18 min（三组并发） | |

全流程：**2.5h → ~18 min**（三组同时跑，取最长组 ~18 min）。

### 7. 不放心的点

- **contextvars 在 `asyncio.create_task` 中自动复制**：Python 3.14 中 `asyncio.Task` 创建时捕获当前 Context。`asyncio.gather` 内部用 `create_task`，自动继承。已验证。
- **MemoryBank 同 user_id 无竞态**：每变体独立 `uid`，`MemoryModule.get_store(uid)` 返回 per-uid store。`
- **TOMLStore concurrent writes**：不同 uid → 不同 `strategies.toml` 路径 → 无竞争。
