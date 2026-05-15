# 实现问题修复 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 修复项目全量分析发现的 13 项实现问题（3 严重、4 中等、6 轻微），排除配置管理部分。

**架构：** 按模块分组修改，每个任务自包含。Memory 模块变更最大（检索拆读写 + 遗忘返回变更集 + 移除双重状态），workflow 变更次之（工具异常 + postprocess 统一 + 死代码）。

**技术栈：** Python 3.14, pytest(asyncio_mode=auto), ruff, ty

---

## 文件结构

| 文件 | 变更类型 | 任务 |
|------|----------|------|
| `app/tools/executor.py` | 修改 | T1 |
| `tests/tools/test_executor.py` | 修改 | T1 |
| `app/agents/workflow.py` | 修改 | T2, T3, T5 |
| `tests/agents/test_workflow_tool.py` | 新建 | T2 |
| `tests/agents/test_rules.py` | 修改 | T3 |
| `app/agents/rules.py` | 修改 | T3, T4 |
| `app/scheduler/scheduler.py` | 修改 | T4, T6 |
| `tests/scheduler/test_tick.py` | 修改 | T4, T6 |
| `app/memory/memory_bank/retrieval.py` | 修改 | T7 |
| `app/memory/memory_bank/store.py` | 修改 | T7, T9 |
| `tests/memory/test_retrieval_pipeline.py` | 修改 | T7 |
| `app/memory/memory_bank/forget.py` | 修改 | T8 |
| `app/memory/memory_bank/lifecycle.py` | 修改 | T8 |
| `tests/memory/test_forgetting.py` | 修改 | T8 |
| `tests/memory/test_memory_bank.py` | 修改 | T9 |
| `app/voice/pipeline.py` | 修改 | T10 |
| `tests/voice/test_pipeline.py` | 修改 | T10 |
| `app/api/main.py` | 修改 | T11 |

---

### 任务 1：修复工具异常处理链 (S1)

**问题：** `executor.py` L114 包装所有异常为 `ToolExecutionError(AppError)` → `workflow.py` L580 re-raise `AppError` 子类 → 工具失败中断后续执行。与 AGENTS.md"不抛"设计矛盾。

**文件：**
- 修改：`app/tools/executor.py:112-116`
- 修改：`app/agents/workflow.py:567-585`
- 新建：`tests/agents/test_workflow_tool.py`
- 修改：`tests/tools/test_executor.py`

- [ ] **步骤 1：编写失败测试 — executor 不包装 AppError**

在 `tests/tools/test_executor.py` 新增测试：handler 抛 `AppError` 子类时，`executor.execute()` 应原样 raise 而非包装为 `ToolExecutionError`。

```python
async def test_app_error_not_wrapped():
    """handler 抛 AppError 子类时应原样传播，不包装为 ToolExecutionError。"""
    from app.exceptions import AppError

    class CustomError(AppError):
        def __init__(self) -> None:
            super().__init__(code="CUSTOM", message="custom error")

    registry = ToolRegistry()
    spec = ToolSpec(
        name="fail_tool",
        description="test",
        input_schema={},
        handler=AsyncMock(side_effect=CustomError()),
    )
    registry.register(spec)
    executor = ToolExecutor(registry)
    with pytest.raises(CustomError):
        await executor.execute("fail_tool", {})
```

- [ ] **步骤 2：运行测试验证失败**

运行：`uv run pytest tests/tools/test_executor.py::test_app_error_not_wrapped -v`
预期：FAIL，`CustomError` 被包装为 `ToolExecutionError`

- [ ] **步骤 3：修改 executor.py 异常处理**

`execute()` 方法 L112-116 改为三档：

```python
        try:
            result = await spec.handler(params)
        except AppError:
            raise
        except ValueError, TypeError:
            msg = f"Tool {tool_name}: invalid params: {e}"
            raise ToolExecutionError(msg) from e
        except Exception as e:
            logger.warning("Tool %s failed: %s", tool_name, e)
            raise ToolExecutionError(str(e)) from e
        else:
            return result
```

需 import `AppError`（已导入）。需在 `except ValueError, TypeError as e:` 中加 `as e`。

- [ ] **步骤 4：运行 executor 测试验证通过**

运行：`uv run pytest tests/tools/test_executor.py -v`
预期：全部 PASS

- [ ] **步骤 5：修改 workflow.py 工具异常处理**

`_handle_tool_calls` 方法 L567-585 改为：

```python
    async def _handle_tool_calls(self, decision: dict) -> None:
        tool_calls = decision.get("tool_calls", [])
        if not tool_calls or not isinstance(tool_calls, list):
            return
        executor = get_default_executor()
        tool_results: list[str] = []
        for tc in tool_calls:
            if isinstance(tc, dict):
                t_name = tc.get("tool", "")
                t_params = tc.get("params", {})
                try:
                    t_result = await executor.execute(t_name, t_params)
                    tool_results.append(f"[{t_name}] {t_result}")
                except WorkflowError:
                    raise
                except ToolExecutionError as e:
                    tool_results.append(f"[{t_name}] 失败: {e}")
                except AppError:
                    raise
        if tool_results:
            logger.info("Tool call results: %s", "; ".join(tool_results))
```

需添加 `from app.tools.executor import ToolExecutionError` 导入。

- [ ] **步骤 6：编写工作流工具异常集成测试**

新建 `tests/agents/test_workflow_tool.py`：

```python
"""工具异常在工作流中的传播测试。"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.exceptions import AppError
from app.tools.executor import ToolExecutionError, ToolExecutor
from app.tools.registry import ToolSpec, ToolRegistry


class TestToolExceptionInWorkflow:
    """工具异常在 _handle_tool_calls 中的处理。"""

    async def test_tool_execution_error_does_not_interrupt(self):
        """ToolExecutionError 追加错误文本，不中断后续工具。"""
        from app.agents.workflow import AgentWorkflow

        registry = ToolRegistry()
        spec_fail = ToolSpec(
            name="fail_tool",
            description="test",
            input_schema={},
            handler=AsyncMock(side_effect=ToolExecutionError("boom")),
        )
        spec_ok = ToolSpec(
            name="ok_tool",
            description="test",
            input_schema={},
            handler=AsyncMock(return_value="ok"),
        )
        registry.register(spec_fail)
        registry.register(spec_ok)

        with patch("app.agents.workflow.get_default_executor", return_value=ToolExecutor(registry)):
            wf = AgentWorkflow.__new__(AgentWorkflow)
            # _handle_tool_calls 只 log 不抛 ToolExecutionError
            await wf._handle_tool_calls({
                "tool_calls": [
                    {"tool": "fail_tool", "params": {}},
                    {"tool": "ok_tool", "params": {}},
                ]
            })

        spec_ok.handler.assert_awaited_once()

    async def test_workflow_error_interrupts(self):
        """WorkflowError 应中断工具执行循环。"""
        from app.agents.workflow import AgentWorkflow, WorkflowError

        registry = ToolRegistry()
        spec = ToolSpec(
            name="wf_fail",
            description="test",
            input_schema={},
            handler=AsyncMock(side_effect=WorkflowError()),
        )
        registry.register(spec)

        with patch("app.agents.workflow.get_default_executor", return_value=ToolExecutor(registry)):
            wf = AgentWorkflow.__new__(AgentWorkflow)
            with pytest.raises(WorkflowError):
                await wf._handle_tool_calls({
                    "tool_calls": [{"tool": "wf_fail", "params": {}}]
                })
```

注意：`ToolExecutionError` 由 executor 内部 `except Exception` 包装产生，handler 直接抛 `ToolExecutionError` 的场景等效。

- [ ] **步骤 7：运行全部相关测试**

运行：`uv run pytest tests/tools/ tests/agents/test_workflow_tool.py -v`
预期：全部 PASS

- [ ] **步骤 8：Commit**

```bash
git add app/tools/executor.py app/agents/workflow.py tests/tools/test_executor.py tests/agents/test_workflow_tool.py
git commit -m "fix(tools): stop re-raising tool errors, match design intent of non-interrupt"
```

---

### 任务 2：统一 postprocess_decision 调用点 (S2) + 删除死代码 (L10, L11)

**问题：** `postprocess_decision` 三处调用分散，每处 `_postprocessed` 标志处理不同。`format_constraints()` 死代码、`_extract_location_target` 死参数。

**文件：**
- 修改：`app/agents/workflow.py`
- 修改：`app/agents/rules.py`

- [ ] **步骤 1：编写失败测试 — postprocess 调用次数验证**

在 `tests/agents/test_rules.py` 末尾新增：

```python
class TestEnsurePostprocessed:
    """_ensure_postprocessed 应统一处理 postprocess + flag。"""

    def test_idempotent(self):
        """已 _postprocessed 的决策不重复调用。"""
        from app.agents.workflow import AgentWorkflow
        decision = {"should_remind": True, "_postprocessed": True}
        ctx = {"scenario": "highway"}
        # 直接调用 postprocess 不会再次修改
        with patch("app.agents.rules.postprocess_decision") as mock_pp:
            # _ensure_postprocessed 应检查 flag 后跳过
            # 先验证当前行为：直接调用 postprocess_decision
            mock_pp.return_value = (decision, [])
            AgentWorkflow._ensure_postprocessed(decision, ctx)
            mock_pp.assert_not_called()
```

注意：此测试在 `_ensure_postprocessed` 实现前会 FAIL（AttributeError）。

- [ ] **步骤 2：在 workflow.py 提取 `_ensure_postprocessed`**

在 `AgentWorkflow` 类中添加静态方法：

```python
    @staticmethod
    def _ensure_postprocessed(
        decision: dict, driving_ctx: dict | None
    ) -> tuple[dict, list[str]]:
        """统一入口：确保 decision 已过规则后处理。幂等。"""
        if decision.get("_postprocessed") or not driving_ctx:
            return decision, []
        decision, modifications = postprocess_decision(decision, driving_ctx)
        decision["_postprocessed"] = True
        return decision, modifications
```

- [ ] **步骤 3：替换三处调用点**

1. `_execution_node` L717-721：
```python
        # 替换
        # if driving_ctx:
        #     if decision.get("_postprocessed"):
        #         modifications = []
        #     else:
        #         decision, modifications = postprocess_decision(decision, driving_ctx)
        # 为：
        decision, modifications = self._ensure_postprocessed(decision, driving_ctx)
```

2. `run_with_stages` L796-800（shortcut 路径）：
```python
        # 替换
        # if driving_context:
        #     shortcut_decision, _modifications = postprocess_decision(
        #         shortcut_decision, driving_context
        #     )
        #     shortcut_decision["_postprocessed"] = True
        # 为：
        shortcut_decision, _modifications = self._ensure_postprocessed(
            shortcut_decision, driving_context
        )
```

3. `proactive_run` L898-900：
```python
        # 替换
        # if stages.context:
        #     decision, _modifications = postprocess_decision(decision, stages.context)
        #     decision["_postprocessed"] = True
        # 为：
        decision, _modifications = self._ensure_postprocessed(decision, stages.context)
```

4. `run_stream` L974-978（shortcut 路径）同理：
```python
        shortcut_decision, _modifications = self._ensure_postprocessed(
            shortcut_decision, driving_context
        )
```

- [ ] **步骤 4：删除 `format_constraints()` 死代码**

在 `rules.py` 删除 L243-258 `format_constraints()` 函数。搜索全项目确认无调用方后删除。

- [ ] **步骤 5：删除 `_extract_location_target` 死参数**

在 `workflow.py` L185，`_extract_location_target(_decision: dict, driving_ctx)` 中 `_decision` 参数未使用。改为 `_extract_location_target(driving_ctx)`，同时更新 `_map_pending_trigger` 中的两处调用（L203, L210）。

- [ ] **步骤 6：运行测试**

运行：`uv run pytest tests/agents/ -v`
预期：全部 PASS

- [ ] **步骤 7：Commit**

```bash
git add app/agents/workflow.py app/agents/rules.py tests/agents/
git commit -m "refactor(agents): unify postprocess entry point, remove dead code"
```

---

### 任务 3：统一疲劳阈值 (S3)

**问题：** `scheduler.py` L29 硬编码 `_FATIGUE_HIGH = 0.7`，`rules.py` 从配置读。

**文件：**
- 修改：`app/scheduler/scheduler.py:29, 209`
- 修改：`tests/scheduler/test_tick.py`

- [ ] **步骤 1：修改 scheduler.py**

删除 L29 `_FATIGUE_HIGH = 0.7`。

在文件顶部添加 import：
```python
from app.agents.rules import get_fatigue_threshold
```

L209 替换 `fatigue > _FATIGUE_HIGH` 为 `fatigue > get_fatigue_threshold()`。

- [ ] **步骤 2：更新 test_tick.py**

如果测试中引用 `_FATIGUE_HIGH`，更新为 mock `get_fatigue_threshold`。搜索测试中是否有直接引用 `_FATIGUE_HIGH`。

- [ ] **步骤 3：运行测试**

运行：`uv run pytest tests/scheduler/ -v`
预期：全部 PASS

- [ ] **步骤 4：Commit**

```bash
git add app/scheduler/scheduler.py tests/scheduler/
git commit -m "fix(scheduler): use shared fatigue threshold from rules engine"
```

---

### 任务 4：Memory 检索拆读写 (M4)

**问题：** `retrieval.py` `_update_memory_strengths()` 检索时原地修改 metadata。

**文件：**
- 修改：`app/memory/memory_bank/retrieval.py:256-290, 409-462`
- 修改：`app/memory/memory_bank/store.py:251-304`
- 修改：`tests/memory/test_retrieval_pipeline.py`

- [ ] **步骤 1：修改 `_update_memory_strengths` 为纯函数**

将 `_update_memory_strengths` 改为不修改 metadata，而是返回变更集：

```python
def _compute_memory_strength_updates(
    results: list[dict],
    metadata: list[dict],
    config: MemoryBankConfig,
    reference_date: str | None = None,
) -> dict[int, dict[str, object]]:
    """计算命中条目的记忆强度更新，返回变更集。不修改 metadata。

    Returns:
        dict[meta_idx → {field: new_value}]
    """
    updates: dict[int, dict[str, object]] = {}
    today = reference_date or datetime.now(UTC).strftime("%Y-%m-%d")
    for r in results:
        all_mi: list[int] = []
        ai = r.get("_all_meta_indices")
        if isinstance(ai, list):
            all_mi.extend(ai)
        else:
            mi = r.get("_meta_idx")
            if mi is not None:
                all_mi.append(mi)
        for mi in all_mi:
            if 0 <= mi < len(metadata) and mi not in updates:
                new_strength = min(
                    _safe_memory_strength(
                        metadata[mi].get("memory_strength", INITIAL_MEMORY_STRENGTH)
                    )
                    + 1.0,
                    float(config.max_memory_strength),
                )
                fields: dict[str, object] = {"memory_strength": new_strength}
                if metadata[mi].get("last_recall_date") != today:
                    fields["last_recall_date"] = today
                updates[mi] = fields
    return updates
```

- [ ] **步骤 2：修改 `RetrievalPipeline.search` 返回变更集**

`search()` 返回类型从 `tuple[list[dict], bool]` 改为 `tuple[list[dict], dict[int, dict[str, object]]]`。

L457-459 替换：
```python
        updates = _compute_memory_strength_updates(
            merged, metadata, self._config, reference_date=reference_date
        )
```

L462 替换返回值：
```python
        return merged, updates
```

- [ ] **步骤 3：修改 `store.py` 的 `search()` 方法**

`store.py` L261 现在接收 `updates` 而非 `_updated`。将 recall boost 应用移到显式步骤：

```python
        results, strength_updates = await self._retrieval.search(
            query,
            top_k,
            reference_date=self._get_reference_date(),
        )
```

在 `await self._maybe_save()` 之前，显式 apply 变更：
```python
        # 回忆强化：显式更新命中条目的记忆强度
        if strength_updates:
            metadata = self._index.get_metadata()
            for mi, fields in strength_updates.items():
                if 0 <= mi < len(metadata):
                    metadata[mi].update(fields)
```

- [ ] **步骤 4：更新 `test_retrieval_pipeline.py`**

搜索 `_update_memory_strengths` 和 `updated` 的引用，更新为新的接口。具体：

- 测试 "updated flag on memory_strength change" 改为检查 `updates` dict 非空
- 测试 "strength capped at max" 改为检查 `updates[idx]["memory_strength"]` 值

接口 + 思路：将断言 `assert updated is True` 改为 `assert len(updates) > 0`。将 `result, updated = await pipeline.search(...)` 改为 `result, updates = await pipeline.search(...)`。

- [ ] **步骤 5：运行 Memory 测试**

运行：`uv run pytest tests/memory/ -v`
预期：全部 PASS

- [ ] **步骤 6：Commit**

```bash
git add app/memory/memory_bank/retrieval.py app/memory/memory_bank/store.py tests/memory/test_retrieval_pipeline.py
git commit -m "refactor(memory): split search read from recall boost write"
```

---

### 任务 5：遗忘返回变更集 (M5)

**问题：** `ForgettingCurve.maybe_forget()` L197 原地修改 metadata。

**文件：**
- 修改：`app/memory/memory_bank/forget.py:149-202`
- 修改：`app/memory/memory_bank/lifecycle.py:57-78`
- 修改：`tests/memory/test_forgetting.py`

- [ ] **步骤 1：修改 `maybe_forget` 返回变更集**

`maybe_forget` 不再原地修改 metadata。返回类型改为 `dict[int, dict[str, object]] | None`（None 表示节流跳过，空 dict 表示无遗忘，非空 dict 为 `{meta_index → {forgotten: True}}` 变更）。

但当前 `maybe_forget` 接收 `metadata: list[dict]` 而非 indices，需要遍历时同时获得 index。修改签名：

```python
    def maybe_forget(
        self, metadata: list[dict], reference_date: str | None = None
    ) -> tuple[list[int], dict[int, dict[str, object]]] | None:
        """返回 (forgotten_faiss_ids, changeset) 或 None（节流）。

        changeset: {meta_index → {"forgotten": True}}
        不修改传入的 metadata。
        """
```

实现思路：遍历 `enumerate(metadata)` 而非 `metadata`，不写 `entry["forgotten"] = True`，改为收集到 changeset 中返回。L197 `entry["forgotten"] = True` 改为 `changes[idx] = {"forgotten": True}`。

- [ ] **步骤 2：修改 `lifecycle.py` `purge_forgotten`**

接收 changeset，apply 到 metadata 后再删除：

```python
    async def purge_forgotten(self, metadata: list[dict]) -> bool:
        result = self._forget.maybe_forget(
            metadata,
            reference_date=self._resolve_reference_date(),
        )
        if result is None:
            return False

        forgotten_ids, changeset = result
        # apply changeset 到 metadata
        for idx, fields in changeset.items():
            if 0 <= idx < len(metadata):
                metadata[idx].update(fields)

        # 确定性模式无 forgotten_ids 时，从已标记条目收集
        if not forgotten_ids:
            forgotten_ids = [m["faiss_id"] for m in metadata if m.get("forgotten")]
        if forgotten_ids:
            if self._metrics:
                self._metrics.forget_count += 1
                self._metrics.forget_removed_count += len(forgotten_ids)
            await self._index.remove_vectors(forgotten_ids)
            return True
        return False
```

- [ ] **步骤 3：更新 `test_forgetting.py`**

搜索 `maybe_forget` 测试用例，更新断言：

- 测试调用后检查 metadata 未被修改（而非检查 `entry["forgotten"] == True`）
- 检查返回的 changeset 包含预期 index
- 检查 forgotten_ids 列表

接口 + 思路：原测试 `assert entry.get("forgotten")` 改为检查 changeset。原 `maybe_forget(metadata)` 返回 `list[int] | None`，现返回 `tuple[list[int], dict] | None`。

- [ ] **步骤 4：运行 Memory 测试**

运行：`uv run pytest tests/memory/ -v`
预期：全部 PASS

- [ ] **步骤 5：Commit**

```bash
git add app/memory/memory_bank/forget.py app/memory/memory_bank/lifecycle.py tests/memory/test_forgetting.py
git commit -m "refactor(memory): return changeset from maybe_forget instead of in-place mutate"
```

---

### 任务 6：移除 `_source_event_index` 双重状态 (M6)

**问题：** `store.py` 维护内存 dict + FAISS metadata 双重状态。

**文件：**
- 修改：`app/memory/memory_bank/store.py`
- 修改：`tests/memory/test_memory_bank.py`

- [ ] **步骤 1：删除 `_source_event_index` 相关代码**

在 `store.py` 中：

1. 删除 `__init__` 中的：
   - L94-96: `_source_event_index` dict 初始化
   - L97: `_source_index_lock`
   - L113: `_source_index_dirty`
   - L43: `_SOURCE_INDEX_FILENAME` 类常量

2. 删除方法：
   - `_load_source_index()` L143-155
   - `_save_source_index()` L157-178

3. 修改 `write()` L198-201：删除 `_source_event_index` 更新块
4. 修改 `write_batch()` L209-212：同上
5. 修改 `write_interaction()` L233-243：删除 `_source_event_index` 读取，仅保留 FAISS metadata 遍历路径

`write_interaction` 修改后：
```python
        # 从 FAISS metadata 查找同 source 的所有事件条目
        date_key = datetime.now(UTC).strftime("%Y-%m-%d")
        event_ids: list[str] = []
        for m in self._index.get_metadata():
            if m.get("source") == date_key and m.get("type") != "daily_summary":
                fid = m.get("faiss_id")
                if fid is not None:
                    event_ids.append(str(fid))
```

6. 修改 `_maybe_save()` L183-189：删除 `_save_source_index()` 调用
7. 修改 `close()` L402-404：删除 `_save_source_index()` 调用

- [ ] **步骤 2：更新 `test_memory_bank.py`**

删除 `source_event_index` 相关测试（save/load/corruption）。搜索测试中所有 `_source_event_index` 引用并删除。

- [ ] **步骤 3：运行 Memory 测试**

运行：`uv run pytest tests/memory/ -v`
预期：全部 PASS

- [ ] **步骤 4：Commit**

```bash
git add app/memory/memory_bank/store.py tests/memory/test_memory_bank.py
git commit -m "refactor(memory): remove dual-state source_event_index, query from FAISS metadata"
```

---

### 任务 7：pending 跳过 LLM (M7)

**问题：** `_poll_pending` 对已确定内容的 reminder 仍过完整三阶段工作流。

**文件：**
- 修改：`app/scheduler/scheduler.py:107-132`
- 修改：`app/agents/workflow.py`（新增方法）
- 修改：`tests/scheduler/test_tick.py`

- [ ] **步骤 1：在 `AgentWorkflow` 新增 `execute_pending_reminder` 方法**

```python
    async def execute_pending_reminder(
        self,
        content: str,
        driving_context: dict | None = None,
        trigger_source: str = "pending_reminder",
    ) -> tuple[str, str | None, WorkflowStages]:
        """对已确定内容的 pending reminder 跳过 LLM，仅走 Execution。"""
        stages = WorkflowStages()
        decision = {
            "should_remind": True,
            "reminder_content": content,
            "action": "remind",
            "timing": "immediate",
            "channel": "audio",
            "_postprocessed": False,
        }
        state: AgentState = {
            "original_query": f"[proactive:{trigger_source}]",
            "context": {},
            "task": None,
            "decision": decision,
            "result": None,
            "event_id": None,
            "driving_context": driving_context,
            "stages": stages,
            "session_id": None,
        }
        try:
            exec_result = await self._execution_node(state)
            state.update(exec_result)
        except Exception as e:
            logger.warning("execute_pending_reminder failed: %s", e)
            return "待触发提醒处理失败", None, stages
        result = state.get("result") or "处理完成"
        event_id = state.get("event_id")
        return result, event_id, stages
```

- [ ] **步骤 2：修改 `scheduler.py` `_poll_pending`**

```python
    async def _poll_pending(self, ctx: dict) -> None:
        if self._pending_manager is None:
            self._pending_manager = PendingReminderManager(
                user_data_dir(self._workflow.current_user)
            )
        pm = self._pending_manager
        triggered = await pm.poll(ctx)
        for tr in triggered:
            content = tr.get("content", "")
            logger.info("PendingReminder triggered: %s", tr.get("id"))
            try:
                if content:
                    # 已有完整内容，跳过 LLM
                    result, event_id, _ = await self._workflow.execute_pending_reminder(
                        content=content,
                        driving_context=ctx,
                    )
                else:
                    # 无内容，走完整工作流
                    result, event_id, _ = await self._workflow.proactive_run(
                        context_override=ctx,
                        trigger_source="pending_reminder",
                    )
                if event_id:
                    logger.info(
                        "PendingReminder executed: %s → %s",
                        tr.get("id"),
                        result,
                    )
            except AppError as e:
                logger.warning("PendingReminder execution failed: %s", e)
```

- [ ] **步骤 3：更新测试**

在 `test_tick.py` 中，更新 `_poll_pending` 相关测试，验证有内容时调 `execute_pending_reminder` 而非 `proactive_run`。

- [ ] **步骤 4：运行测试**

运行：`uv run pytest tests/scheduler/ tests/agents/ -v`
预期：全部 PASS

- [ ] **步骤 5：Commit**

```bash
git add app/scheduler/scheduler.py app/agents/workflow.py tests/scheduler/
git commit -m "feat(scheduler): skip LLM for determined pending reminders"
```

---

### 任务 8：拆分 `_execution_node` (L8)

**问题：** 63 行，含五个分支。

**文件：**
- 修改：`app/agents/workflow.py:707-770`

- [ ] **步骤 1：提取辅助方法**

在 `_execution_node` 之前添加两个辅助方法：

```python
    async def _execute_tools(self, decision: dict) -> None:
        """执行工具调用（如有）。"""
        await self._handle_tool_calls(decision)

    def _resolve_rules(self, state: AgentState, driving_ctx: dict | None) -> dict:
        """从 state 获取规则结果，若无则重新应用。"""
        if "rules_result" in state:
            return state["rules_result"] or {}
        rules_result = apply_rules(driving_ctx) if driving_ctx else {}
        state["rules_result"] = rules_result
        return rules_result
```

- [ ] **步骤 2：简化 `_execution_node`**

```python
    async def _execution_node(self, state: AgentState) -> dict:
        decision = state.get("decision") or {}
        stages = state.get("stages")

        action = decision.get("action", "")
        if action == "cancel_last":
            return await self._handle_cancel(state, stages)

        driving_ctx = state.get("driving_context")
        decision, modifications = self._ensure_postprocessed(decision, driving_ctx)

        if stages is not None:
            stages.decision = decision

        if not decision.get("should_remind", True):
            result = "提醒已取消：安全规则禁止发送"
            if stages is not None:
                stages.execution = {"content": None, "event_id": None, "result": result, "modifications": modifications}
            return {"result": result, "event_id": None}

        await self._execute_tools(decision)

        rules_result = self._resolve_rules(state, driving_ctx)
        postpone = decision.get("postpone", False)
        timing = decision.get("timing", "")

        if postpone or timing in ("delay", "location", "location_time"):
            return await self._handle_postpone(decision, state, driving_ctx, rules_result, modifications, stages)

        freq_msg = await self._check_frequency_guard(state)
        if freq_msg is not None:
            if stages is not None:
                stages.execution = {"content": None, "event_id": None, "result": freq_msg, "modifications": modifications}
            return {"result": freq_msg, "event_id": None}

        return await self._handle_immediate_send(decision, state, driving_ctx, rules_result, modifications, stages)
```

注意：此步骤应在任务 2（_ensure_postprocessed 提取）完成后执行，因为已使用 `_ensure_postprocessed`。

- [ ] **步骤 2：运行测试**

运行：`uv run pytest tests/agents/ -v`
预期：全部 PASS

- [ ] **步骤 3：Commit**

```bash
git add app/agents/workflow.py
git commit -m "refactor(agents): extract helpers from _execution_node for clarity"
```

---

### 任务 9：帧大小动态计算 (L9)

**问题：** `pipeline.py` L54 硬编码 30ms。

**文件：**
- 修改：`app/voice/pipeline.py:53-54`
- 修改：`tests/voice/test_pipeline.py`

- [ ] **步骤 1：修改帧时长计算**

L53-54 替换：
```python
        silence_ms = cfg.get("silence_timeout_ms", 500)
        silence_frames = max(1, silence_ms // 30)
```
为：
```python
        silence_ms = cfg.get("silence_timeout_ms", 500)
        frame_ms = cfg.get("frame_ms", 30)
        silence_frames = max(1, silence_ms // frame_ms)
```

注意：`config/voice.toml` 当前无 `frame_ms` 配置项。VADEngine 的帧时长由 `sample_rate * 2 / 1000 * frame_ms` 计算。VoicePipeline 从 `self._vad.frame_bytes` 读取帧大小用于校验。`silence_frames` 的计算需要与 VADEngine 内部一致。

检查 VADEngine：`_FRAMES_PER_CHUNK = 480`（即 30ms at 16kHz）。如果 `frame_ms` 改变，`_FRAMES_PER_CHUNK` 也变。但 VADEngine 构造函数不接收 `frame_ms` 参数。最简方案：`silence_frames = max(1, silence_ms * sample_rate // (1000 * self._vad._frames_per_chunk))`... 但这访问私有属性。

**更简洁方案**：从 `_vad.frame_bytes` 反推帧时长。`frame_bytes = sample_rate * 2 * frame_ms / 1000`，所以 `frame_ms = frame_bytes * 1000 / (sample_rate * 2)`。

```python
        silence_ms = cfg.get("silence_timeout_ms", 500)
        frame_bytes = self._vad.frame_bytes
        frame_ms = max(1, frame_bytes * 1000 // (sample_rate * 2))
        silence_frames = max(1, silence_ms // frame_ms)
```

但这需要先创建 VADEngine。检查构造函数顺序：L56-59 创建 `_vad`，L54 在之前。需要将 `silence_frames` 计算移到 `_vad` 创建之后。

修改后的 `__init__` 片段：
```python
        self._vad = VADEngine(
            mode=vad_mode,
            sample_rate=sample_rate,
            silence_timeout_frames=0,  # 临时值，下面重新计算
        )
        # 从 VAD 帧大小反推帧时长，避免硬编码 30ms
        frame_ms = max(1, self._vad.frame_bytes * 1000 // (sample_rate * 2))
        self._vad._silence_timeout = max(1, silence_ms // frame_ms)  # noqa: SLF001
```

但 `_silence_timeout` 是私有属性... 检查 VADEngine 构造函数接受 `silence_timeout_frames` 参数。方案：先算再传。

```python
        # 先创建临时 VAD 获取帧大小，或直接计算
        frame_ms = cfg.get("frame_ms", 30)
        silence_ms = cfg.get("silence_timeout_ms", 500)
        silence_frames = max(1, silence_ms // frame_ms)

        self._vad = VADEngine(
            mode=vad_mode,
            sample_rate=sample_rate,
            silence_timeout_frames=silence_frames,
        )
```

这是最简方案。`frame_ms` 从配置读，默认 30ms（与当前硬编码一致）。未来配置变更时自动适配。

- [ ] **步骤 2：更新测试**

`test_pipeline.py` 中如有硬编码帧相关的测试，确保通过。Pipeline 测试主要通过 `__new__` + 手动设置属性，不受此变更影响。

- [ ] **步骤 3：运行测试**

运行：`uv run pytest tests/voice/ -v`
预期：全部 PASS

- [ ] **步骤 4：Commit**

```bash
git add app/voice/pipeline.py
git commit -m "fix(voice): calculate silence frames from config frame_ms instead of hardcoded 30ms"
```

---

### 任务 10：封装修复 + logging 移除 (L12, L13)

**问题：** `main.py` L144 直接索引 `_memory_module_state[0]`，L37 模块级 `logging.basicConfig`。

**文件：**
- 修改：`app/api/main.py:32, 37, 144`
- 修改：`app/config.py`

- [ ] **步骤 1：替换 `_memory_module_state[0]` 为 `get_memory_module()`**

`main.py` L32 删除 `from app.memory.singleton import _memory_module_state`。L105 已有 `from app.memory.singleton import get_memory_module`，合并。

L144 替换：
```python
    mm = _memory_module_state[0]
```
为：
```python
    mm = get_memory_module()
```

但需注意：`get_memory_module()` 在未初始化时会创建新实例。而 `_memory_module_state[0]` 在关闭时可能已被设为 None。检查 `close_memory_module()` L41 `_memory_module_state[0] = None`。

需要改用不同方式：singleton 导出一个 `get_memory_module_if_initialized()` 方法，或直接使用 `close_memory_module()`。

**方案**：lifespan 关闭时直接调 `close_memory_module()`，替代手动索引：

```python
    # 替换 mm = _memory_module_state[0] ... if mm is not None: await mm.close()
    # 为：
    from app.memory.singleton import close_memory_module
    await close_memory_module()
    logger.info("MemoryModule closed")
```

- [ ] **步骤 2：移除模块级 `logging.basicConfig`**

删除 `main.py` L37 `logging.basicConfig(level=logging.INFO)`。

在 `app/config.py` 添加 logging 配置函数：

```python
import logging

def setup_logging() -> None:
    """配置应用级日志。仅在 main.py 入口调用一次。"""
    logging.basicConfig(level=logging.INFO)
```

在 `main.py` 的 `app = FastAPI(...)` 之前调用 `setup_logging()`：
```python
from app.config import setup_logging
setup_logging()
```

或在 `main.py`（根目录）中调用，因为那是真正的进程入口。

**方案**：在 `main.py`（根）中调用更合适，因为它是进程入口。

- [ ] **步骤 3：运行测试**

运行：`uv run pytest tests/api/ -v`
预期：全部 PASS

- [ ] **步骤 4：Commit**

```bash
git add app/api/main.py app/config.py
git commit -m "fix(api): use close_memory_module instead of internal state index, move logging setup"
```

---

### 任务 11：全量验证

- [ ] **步骤 1：运行 ruff**

```bash
uv run ruff check --fix && uv run ruff format
```

- [ ] **步骤 2：运行 ty**

```bash
uv run ty check
```

- [ ] **步骤 3：运行 pytest**

```bash
uv run pytest
```

- [ ] **步骤 4：确认全部通过**

如有失败，修复后重跑。
