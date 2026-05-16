# 实验正确性问题修复实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 修复消融实验和 VehicleMemBench 集成中 7 个正确性问题，同步执行代码质量、测试、文档优化。

**架构：** 修改集集中于 `experiments/` 子包——不触及 `app/` 核心代码。问题 4（memory_strength）为 VehicleMemBench 适配器，其余为消融实验。测试追加至 `tests/experiments/`。

**技术栈：** Python 3.14, pytest, ruff, ty

---

### 文件清单

| 操作 | 文件 | 变更概要 |
|------|------|----------|
| 修改 | `experiments/ablation/feedback_simulator.py` | export/restore_state + has_visual_content 简化 |
| 修改 | `experiments/ablation/_io.py` | append/load checkpoint 支持 extra |
| 修改 | `experiments/ablation/personalization_group.py` | 续跑状态恢复 + pers_stratum 修复 |
| 修改 | `experiments/ablation/preference_metrics.py` | has_visual_content 调用方更新 |
| 修改 | `experiments/ablation/safety_group.py` | safety_stratum 类型防御 |
| 修改 | `experiments/ablation/architecture_group.py` | arch_stratum 类型防御 |
| 修改 | `experiments/ablation/ablation_runner.py` | 架构组 memory_context 对齐 |
| 修改 | `experiments/vehicle_mem_bench/adapter.py` | memory_strength 差异化 |
| 修改 | `experiments/vehicle_mem_bench/__main__.py` | run-all --benchmark-dir |
| 修改 | `experiments/ablation/AGENTS.md` | 文档更新 |
| 修改 | `experiments/vehicle_mem_bench/AGENTS.md` | 文档更新 |
| 新建 | `tests/experiments/test_ablation_correctness.py` | 回归测试 |

---

### 任务 1：feedback_simulator 增加状态导出/恢复 + has_visual_content 简化

**文件：**
- 修改：`experiments/ablation/feedback_simulator.py:60-170`

- [ ] **步骤 1：编写失败的测试**

```python
# tests/experiments/test_ablation_correctness.py
"""消融实验正确性修复回归测试."""


def test_has_visual_content_no_stages():
    from experiments.ablation.feedback_simulator import has_visual_content

    assert has_visual_content({"reminder_content": {"display_text": "前方拥堵"}}) is True
    assert has_visual_content({"reminder_content": {"display_text": ""}}) is False
    assert has_visual_content({"reminder_content": {}}) is False
    assert has_visual_content({}) is False


def test_export_restore_feedback_state_roundtrip():
    from experiments.ablation.feedback_simulator import (
        _current_delta,
        _recent_feedback,
        export_state,
        restore_state,
    )

    _current_delta[("test_user", "meeting")] = 0.25
    _recent_feedback[("test_user", "meeting")] = [1, -1, 1]

    state = export_state()
    assert state["_current_delta"]["test_user::meeting"] == 0.25
    assert state["_recent_feedback"]["test_user::meeting"] == [1, -1, 1]

    _current_delta.clear()
    _recent_feedback.clear()
    restore_state(state)
    assert _current_delta[("test_user", "meeting")] == 0.25
    assert _recent_feedback[("test_user", "meeting")] == [1, -1, 1]

    # cleanup
    _current_delta.clear()
    _recent_feedback.clear()
```

- [ ] **步骤 2：运行测试验证失败**

运行：`uv run pytest tests/experiments/test_ablation_correctness.py::test_has_visual_content_no_stages -v`
预期：FAIL（函数签名含 stages 参数，无 stages 调用报 TypeError）

运行：`uv run pytest tests/experiments/test_ablation_correctness.py::test_export_restore_feedback_state_roundtrip -v`
预期：FAIL（export_state/restore_state 未定义）

- [ ] **步骤 3：实现 has_visual_content 简化**

修改 `feedback_simulator.py:130-151`：

```python
def has_visual_content(decision: dict) -> bool:
    """判断 LLM 是否意图生成视觉内容."""
    rc = decision.get("reminder_content")
    if not isinstance(rc, dict):
        return False
    display = rc.get("display_text")
    detailed = rc.get("detailed")
    return bool(
        (isinstance(display, str) and display.strip())
        or (isinstance(detailed, str) and detailed.strip())
    )
```

注意：删除 stages 参数。`simulate_feedback` 中调用处改为 `has_visual_content(decision)`。

- [ ] **步骤 4：实现 export_state / restore_state**

在 `feedback_simulator.py` 模块末尾追加：

```python
def export_state() -> dict:
    """导出当前反馈状态以备持久化.
    
    Returns:
        {"_current_delta": {...}, "_recent_feedback": {...}}
        键为 "user_id::task_type" 格式的字符串（dict key 直序列化）。
    """
    return {
        "_current_delta": {
            f"{uid}::{tt}": v for (uid, tt), v in _current_delta.items()
        },
        "_recent_feedback": {
            f"{uid}::{tt}": v for (uid, tt), v in _recent_feedback.items()
        },
    }


def restore_state(state: dict) -> None:
    """从持久化状态恢复反馈状态。幂等——不破坏已有状态。"""
    _current_delta.clear()
    _recent_feedback.clear()
    for key_str, val in state.get("_current_delta", {}).items():
        if "::" in key_str:
            uid, tt = key_str.split("::", 1)
            _current_delta[(uid, tt)] = float(val)
    for key_str, val in state.get("_recent_feedback", {}).items():
        if "::" in key_str:
            uid, tt = key_str.split("::", 1)
            _recent_feedback[(uid, tt)] = [int(v) for v in val if isinstance(v, int)]
```

- [ ] **步骤 5：运行测试验证通过**

运行：`uv run pytest tests/experiments/test_ablation_correctness.py::test_has_visual_content_no_stages tests/experiments/test_ablation_correctness.py::test_export_restore_feedback_state_roundtrip -v`
预期：PASS

- [ ] **步骤 6：Commit**

```bash
git add experiments/ablation/feedback_simulator.py tests/experiments/test_ablation_correctness.py
git commit -m "fix(ablation): add feedback state export/restore, simplify has_visual_content"
```

---

### 任务 2：_io.py checkpoint 支持 extra 字段

**文件：**
- 修改：`experiments/ablation/_io.py:199-252`

- [ ] **步骤 1：修改 append_checkpoint**

`_io.py:199-217`，在 record dict 中增加 extra 字段：

```python
async def append_checkpoint(
    path: Path, vr: VariantResult, *, include_modifications: bool = False, extra: dict | None = None
) -> None:
    """追加写单条 VariantResult 到 checkpoint JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    record: dict[str, object] = {
        "scenario_id": vr.scenario_id,
        "variant": vr.variant.value,
        "decision": vr.decision,
        "stages": vr.stages,
        "latency_ms": vr.latency_ms,
        "round_index": vr.round_index,
        "result_text": vr.result_text,
        "event_id": vr.event_id,
    }
    if include_modifications:
        record["modifications"] = vr.modifications
    if extra:
        record["extra"] = extra
    async with aiofiles.open(path, "a", encoding="utf-8") as f:
        await f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
```

- [ ] **步骤 2：修改 load_checkpoint 返回类型**

`_io.py:167-196`，返回值增加 extra：

```python
async def load_checkpoint(
    path: Path,
) -> tuple[set[tuple[str, str]], list[VariantResult], dict | None]:
    """读取 JSONL checkpoint。Returns: (已完成id集合, VariantResult列表, 最后一条extra状态|None)."""
    ids: set[tuple[str, str]] = set()
    results: list[VariantResult] = []
    last_extra: dict | None = None
    try:
        async with aiofiles.open(path, encoding="utf-8") as f:
            async for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    d = json.loads(stripped)
                    ids.add((d["scenario_id"], d["variant"]))
                    results.append(variant_result_from_dict(d))
                    if "extra" in d and isinstance(d["extra"], dict):
                        last_extra = d["extra"]
                except json.JSONDecodeError, KeyError, ValueError:
                    logger.warning("跳过无效 checkpoint 行: %s", stripped[:80])
                    continue
    except FileNotFoundError:
        ...
        return ids, results, None
    except OSError:
        ...
        return set(), [], None
    return ids, results, last_extra
```

- [ ] **步骤 3：更新 ablation_runner.py 中的调用方**

`ablation_runner.py:217`，load_checkpoint 现在返回三元组：

```python
raw_ids, raw_results, _ = await load_checkpoint(checkpoint_path)
```

（第三个返回值用 _ 忽略——ablation_runner 不需要 extra 状态，仅 personalization_group 需要。）

- [ ] **步骤 4：运行现有测试验证无回归**

运行：`uv run pytest tests/ -q`
预期：596 passed

- [ ] **步骤 5：Commit**

```bash
git add experiments/ablation/_io.py experiments/ablation/ablation_runner.py
git commit -m "fix(ablation): add extra field to checkpoint for feedback state persistence"
```

---

### 任务 3：personalization_group 续跑状态恢复 + pers_stratum 修复

**文件：**
- 修改：`experiments/ablation/personalization_group.py:55-175`

- [ ] **步骤 1：修复 pers_stratum**

`personalization_group.py:55-57`：

```python
def pers_stratum(s: Scenario) -> str:
    """个性化组分层键——按合成维度任务类型分组，确保确定性。"""
    dims = s.synthesis_dims
    if dims:
        return dims.get("task_type", "unknown")
    return "unknown"
```

- [ ] **步骤 2：run_personalization_group 开始处增加状态恢复**

在 `personalization_group.py:76` （`all_results: list[VariantResult] = []`）之后插入：

```python
# 续跑：从 checkpoint 恢复反馈状态（自适应步长 + 近期方向）
checkpoint_path = output_path.with_suffix(".checkpoint.jsonl")
if checkpoint_path.exists():
    _, _, last_extra = await load_checkpoint(checkpoint_path)
    if last_extra:
        restore_state(last_extra)
```

需要新增导入：`from ._io import load_checkpoint`（当前文件已导入 `append_checkpoint`，需补充 `load_checkpoint`）。

需要新增导入：`from .feedback_simulator import ..., restore_state`。

- [ ] **步骤 3：每轮 checkpoint 附带 extra 状态**

`personalization_group.py:140` 的 `append_checkpoint` 调用改为：

```python
await append_checkpoint(
    output_path.with_suffix(".checkpoint.jsonl"),
    vr,
    include_modifications=True,
    extra=export_state(),
)
```

新增导入：`from .feedback_simulator import ..., export_state`。

- [ ] **步骤 4：更新 preference_metrics.py 中 has_visual_content 调用**

`preference_metrics.py:102`：

```python
if stage == "visual-detail":
    return has_visual_content(decision)
```

删除 stages 参数。

- [ ] **步骤 5：运行测试验证**

运行：`uv run pytest tests/experiments/ -v`

- [ ] **步骤 6：Commit**

```bash
git add experiments/ablation/personalization_group.py experiments/ablation/preference_metrics.py
git commit -m "fix(ablation): persist feedback state in checkpoint, fix pers_stratum determinism"
```

---

### 任务 4：safety_stratum / arch_stratum 类型防御

**文件：**
- 修改：`experiments/ablation/safety_group.py:21-36`
- 修改：`experiments/ablation/architecture_group.py:24-42`

- [ ] **步骤 1：safety_stratum 加防御**

`safety_group.py:32` 的 `float(d["fatigue_level"])` 改为：

```python
def _safe_fatigue(d: dict) -> float:
    try:
        return float(d.get("fatigue_level", 0.5))
    except (ValueError, TypeError):
        return 0.5
```

替换使用点：`if _safe_fatigue(d) > get_fatigue_threshold():`

- [ ] **步骤 2：arch_stratum 加防御**

`architecture_group.py:40` 的 `float(dims.get("fatigue_level", 0))` 已有 fallback 0，但 `classify_complexity` 中无防御。改为：

```python
def _safe_fatigue(d: dict) -> float:
    try:
        return float(d.get("fatigue_level", 0))
    except (ValueError, TypeError):
        return 0.0
```

替换使用点：`_safe_fatigue(dims) > get_fatigue_threshold()`

- [ ] **步骤 3：编写测试**

`tests/experiments/test_ablation_correctness.py` 追加：

```python
def test_safety_stratum_handles_non_float_fatigue():
    from experiments.ablation.safety_group import safety_stratum
    from experiments.ablation.types import Scenario

    s = Scenario(
        id="test",
        driving_context={},
        user_query="test",
        expected_decision={},
        expected_task_type="other",
        safety_relevant=True,
        scenario_type="city_driving",
        synthesis_dims={"scenario": "highway", "fatigue_level": "invalid", "workload": "normal"},
    )
    result = safety_stratum(s)
    assert "highway" in result  # scenario 部分正常
    # fatigue_level 为 "invalid" 转 float 失败，回退 0.5，不大于阈值，不追加 high_fatigue
    assert "high_fatigue" not in result


def test_pers_stratum_uses_synthesis_dims():
    from experiments.ablation.personalization_group import pers_stratum
    from experiments.ablation.types import Scenario

    s = Scenario(
        id="test",
        driving_context={},
        user_query="test",
        expected_decision={},
        expected_task_type="llm_may_be_wrong",
        safety_relevant=False,
        scenario_type="city_driving",
        synthesis_dims={"scenario": "city_driving", "task_type": "meeting"},
    )
    assert pers_stratum(s) == "meeting"
    # 即使 expected_task_type 不同，pers_stratum 使用合成维度
```

- [ ] **步骤 4：运行测试**

运行：`uv run pytest tests/experiments/test_ablation_correctness.py -v`
预期：全部 PASS

- [ ] **步骤 5：Commit**

```bash
git add experiments/ablation/safety_group.py experiments/ablation/architecture_group.py tests/experiments/test_ablation_correctness.py
git commit -m "fix(ablation): add type defense for fatigue_level in stratum functions"
```

---

### 任务 5：架构组 memory_context 对齐 + current_datetime 注入

**文件：**
- 修改：`experiments/ablation/ablation_runner.py:120-197`

- [ ] **步骤 1：_run_single_llm 中 memory_context 格式对齐 ContextAgent**

当前 `_run_single_llm` 中 memory_context 构建：

```python
if mem_results:
    texts: list[str] = []
    for r in mem_results:
        content = getattr(r, "content", None) or {}
        text = content.get("text", "") if isinstance(content, dict) else ""
        if text:
            texts.append(text)
    if texts:
        user_msg_data["memory_context"] = "; ".join(texts)
```

ContextAgent 的 `_format_memory_for_context` 格式（`app/agents/context_agent.py`）对每条记忆使用：

```python
f"[{event_type}] {text}"  # 含事件类型前缀
```

修改为对齐格式：

```python
if mem_results:
    texts: list[str] = []
    for r in mem_results:
        content = getattr(r, "content", None) or {}
        event_type = getattr(r, "event_type", "")
        text = content.get("text", "") if isinstance(content, dict) else ""
        if text:
            prefix = f"[{event_type}] " if event_type else ""
            texts.append(f"{prefix}{text}")
    if texts:
        user_msg_data["memory_context"] = "\n".join(texts)
```

（换行分隔替换分号分隔，与 ContextAgent 的 `related_events` 格式一致。）

- [ ] **步骤 2：注入 current_datetime 到 user_msg_data**

ContextAgent 在 context dict 中输出 `current_datetime` 字段。`_run_single_llm` 当前仅在 system prompt 中注入（通过 `SINGLE_LLM_SYSTEM_PROMPT.format(current_datetime=now)`），但 user_msg_data JSON 中缺失。追加：

```python
user_msg_data["current_datetime"] = now
```

放在 `user_msg_data` 构建之后、`json.dumps` 之前。`now` 变量已在函数开头定义（`datetime.now(tz=UTC).strftime(...)`）。

- [ ] **步骤 3：确认 ContextAgent 格式**

先确认 `app/agents/context_agent.py` 中 memory 格式。在 `_run_single_llm` 旁加注释引用源文件行号，但不做实际运行时检查——合成场景无历史记忆，对齐为代码路径同一性。

- [ ] **步骤 4：运行现有测试**

运行：`uv run pytest tests/ -q`
预期：无回归

- [ ] **步骤 5：Commit**

```bash
git add experiments/ablation/ablation_runner.py
git commit -m "fix(ablation): align SingleLLM memory_context format with ContextAgent, inject current_datetime"
```

---

### 任务 6：VehicleMemBench memory_strength 差异化

**文件：**
- 修改：`experiments/vehicle_mem_bench/adapter.py:96-148`

- [ ] **步骤 1：_async_add 增加 strength 参数**

`adapter.py:139-148`：

```python
async def _async_add(self, content: str, strength: int = 3) -> str:
    await self._ensure_store()
    assert self._store is not None
    event = MemoryEvent(
        content=content,
        type="passive_voice",
        created_at=datetime.now(UTC).isoformat(),
        memory_strength=strength,
    )
    return await self._store.write(event)
```

同步更新 `add` 方法（公开同步接口）：

```python
def add(self, content: str, strength: int = 3, **kwargs: object) -> str:
    del kwargs
    return self._run(self._async_add(content, strength))
```

- [ ] **步骤 2：processor 中检测 explicit preference**

`adapter.py:213-230` 的 `processor` 闭包中，插入 strength 判定：

```python
_PREFERENCE_KEYWORDS = frozenset({
    "设置", "改成", "调", "偏好", "喜欢", "换成", "切换", "设定",
    "改成", "调整", "改为", "选择", "想要",
})

def _has_explicit_preference(content: str) -> bool:
    return any(kw in content for kw in _PREFERENCE_KEYWORDS)
```

在 `processor` 闭包中：

```python
for bucket in load_hourly_history(history_path):
    content = "\n".join(bucket.lines)
    strength = 5 if _has_explicit_preference(content) else 3
    client.add(content=content, strength=strength)
    message_count += 1
```

- [ ] **步骤 3：运行现有测试**

运行：`uv run pytest tests/ -q`
预期：无回归

- [ ] **步骤 4：Commit**

```bash
git add experiments/vehicle_mem_bench/adapter.py
git commit -m "fix(vmb): differentiate memory_strength by explicit preference keywords"
```

---

### 任务 7：VehicleMemBench run-all --benchmark-dir CLI 参数

**文件：**
- 修改：`experiments/vehicle_mem_bench/__main__.py:178-375`

- [ ] **步骤 1：argparse 增加参数**

`__main__.py:178-193` 的 `run-all` parser：

```python
all_p.add_argument("--benchmark-dir", "--benchmark_dir", type=str, default=None)
```

- [ ] **步骤 2：_cmd_run_all 使用参数**

`__main__.py:296`：

```python
benchmark_dir = args.benchmark_dir or str(vmb_root / "benchmark" / "qa_data")
```

同步更新 model 评测循环中传递给 model_evaluation 的 benchmark_dir——当前已用 `benchmark_dir` 变量，仅需修改该变量来源。

- [ ] **步骤 3：Commit**

```bash
git add experiments/vehicle_mem_bench/__main__.py
git commit -m "feat(vmb): add --benchmark-dir to run-all subcommand"
```

---

### 任务 8：文档同步

**文件：**
- 修改：`experiments/ablation/AGENTS.md`
- 修改：`experiments/vehicle_mem_bench/AGENTS.md`

- [ ] **步骤 1：更新 ablation AGENTS.md**

在 Checkpoint 续跑章节末尾追加：

```markdown
个性化组 checkpoint 额外记录反馈自适应步长状态（`_current_delta` / `_recent_feedback`），
续跑时自动恢复，保证中断后权重更新一致。
```

在个性化组章节末尾追加：

```markdown
`pers_stratum()` 使用合成维度 `task_type`（非 LLM 输出 `expected_task_type`），保证分层确定性。
```

- [ ] **步骤 2：更新 vehicle_mem_bench AGENTS.md**

在用法章节 `run-all` 行后追加：

```bash
# 指定 benchmark 目录
python -m experiments.vehicle_mem_bench run-all --benchmark-dir /custom/qa_data
```

在适配器接口表格 `run_add` 行追加注释：

```markdown
| `run_add` | history → MemoryBankStore | 显式偏好关键词自动设 memory_strength=5，其余=3 |
```

- [ ] **步骤 3：Commit**

```bash
git add experiments/ablation/AGENTS.md experiments/vehicle_mem_bench/AGENTS.md
git commit -m "docs: update AGENTS.md for experiment fixes"
```

---

### 最终验证

- [ ] **步骤 1：运行全量测试**

```bash
uv run pytest tests/ -q
```

预期：≥596 passed，0 failed

- [ ] **步骤 2：运行 lint/format/type check**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```

- [ ] **步骤 3：最终 commit**

（如有 lint/format 修正）

```bash
git add -u && git commit -m "chore: final lint/format fixes"
```
