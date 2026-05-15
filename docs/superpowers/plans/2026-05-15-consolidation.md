# 代码整合与范式统一实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 统一异常体系、拆分 workflow.py、接线配置、修复时区、补全测试覆盖。

**架构：** 新增 `AppError(Exception)` 基类串联四套异常体系；API 层现有 `AppError(HTTPException)` 改为多重继承 `AppError + HTTPException`；`_execution_node()` 拆为子方法 + rules 缓存；scheduler/tools.toml/voice.toml 配置字段接入代码；scheduler/executor/voice 三模块补测试。

**技术栈：** Python 3.14, pytest, ruff, ty

---

## 文件结构

| 操作 | 文件 | 职责变更 |
|------|------|---------|
| 新建 | `app/exceptions.py` | `AppError` 基类 |
| 新建 | `app/utils.py` | `_haversine()` 统一实现 |
| 修改 | `app/memory/exceptions.py` | `MemoryBankError` → 继承 `AppError` |
| 修改 | `app/models/chat.py` | `ChatError` 层级 → 继承 `AppError` |
| 修改 | `app/tools/executor.py` | `ToolExecutionError` → 继承 `AppError` |
| 修改 | `app/agents/workflow.py` | 删弃用代码、拆 `_execution_node`、rules 缓存、异常改 catch |
| 修改 | `app/agents/pending.py` | `_PER_USER_LOCKS` 改 WeakValueDictionary、删除 `_haversine` |
| 修改 | `app/agents/probabilistic.py` | key 统一为 `driver` |
| 修改 | `app/api/errors.py` | `safe_call()` 替代 `safe_memory_call()` |
| 修改 | `app/api/v1/query.py` | 用 `safe_call` |
| 修改 | `app/api/v1/feedback.py` | 用 `safe_call` |
| 修改 | `app/api/v1/data.py` | 用 `safe_call` |
| 修改 | `app/scheduler/scheduler.py` | 配置接线、异常改 catch |
| 修改 | `app/scheduler/context_monitor.py` | 删除 `_haversine`，改导入 |
| 修改 | `app/tools/tools/__init__.py` | `enabled` 接线 |
| 修改 | `app/tools/tools/communication.py` | 配置缓存 |
| 修改 | `app/voice/pipeline.py` | 统一加载 config |
| 修改 | `app/voice/vad.py` | 接受外部计算 frame_bytes |
| 修改 | `app/voice/constants.py` | 删除 `_FRAME_BYTES` |
| 修改 | `app/storage/jsonl_store.py` | mkdir 移到 __init__ |
| 修改 | `app/storage/experiment_store.py` | 改 aiofiles |
| 新建 | `tests/scheduler/test_tick.py` | scheduler 全面测试 |
| 新建 | `tests/tools/test_executor.py` | executor 全面测试 |
| 新建 | `tests/voice/test_pipeline.py` | pipeline 测试 |

---

## 阶段一：基础文件

### 任务 1：创建 `app/exceptions.py`

**文件：**
- 创建：`app/exceptions.py`

- [ ] **步骤 1：创建 `AppError` 基类**

**命名冲突解决方案**：`app/api/errors.py` 已有 `AppError(HTTPException)`。本文件定义的 `AppError(Exception)` 作为全局基类，API 层的 `AppError` 改为多重继承 `AppError + HTTPException`（见任务 7）。导入时：模块层 `from app.exceptions import AppError`；API 层 `from app.api.errors import AppError`（已是子类，`isinstance` 检查兼容）。

```python
"""全系统异常基类。各模块异常继承此类实现统一异常体系。"""


class AppError(Exception):
    """全系统异常基类。

    携带机器可读 code + 人类可读 message。
    API 层 safe_call() 按子类型映射 HTTP 状态码。
    各模块异常（MemoryBankError/ChatError/ToolExecutionError/WorkflowError）继承此类。
    API 层 AppError(HTTPException) 也多重继承此类。
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)
```

- [ ] **步骤 2：运行 ruff + ty 检查**

```bash
uv run ruff check --fix app/exceptions.py && uv run ruff format app/exceptions.py && uv run ty check
```

- [ ] **步骤 3：Commit**

```bash
git add app/exceptions.py && git commit -m "feat: add AppError base class for unified exceptions"
```

---

### 任务 2：创建 `app/utils.py`

**文件：**
- 创建：`app/utils.py`

- [ ] **步骤 1：提取 `_haversine` 到 `app/utils.py`**

从 `app/agents/pending.py` 复制 `_haversine` 实现（完全相同）。

```python
"""项目级工具函数。"""

import math


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """返回两点间距离（米）。"""
    earth_radius_m = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    )
    return earth_radius_m * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
```

- [ ] **步骤 2：运行检查 + commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
git add app/utils.py && git commit -m "feat: add shared haversine utility"
```

---

## 阶段二：异常继承迁移

### 任务 3：Memory 异常迁移

**文件：**
- 修改：`app/memory/exceptions.py`

- [ ] **步骤 1：修改 `MemoryBankError` 继承 `AppError`**

先验证 `MemoryBankError` 是否有直接实例化：
```bash
rg "MemoryBankError\(" app/ tests/ --type py | grep -v "class " | grep -v "import"
```
确认无直接 `raise MemoryBankError(...)` 用法后安全改基类。若存在，需补充 `code` 参数。

```python
# app/memory/exceptions.py 顶部新增导入
from app.exceptions import AppError

# 改第 4 行
class MemoryBankError(AppError):
    """MemoryBank 异常基类。"""
```

`MemoryBankError.__init__` 当前无显式构造函数（仅 `pass`），继承 `AppError.__init__(code, message)` 签名。子类如 `TransientError` 有自己的 `__init__`。各子类 `super().__init__()` 调用中补充 `code` 参数：

- `TransientError.__init__` → `super().__init__(code="MEMORY_TRANSIENT", message=message)`
- `FatalError` → 无 `__init__`，需添加：`def __init__(self, message: str) -> None: super().__init__(code="MEMORY_FATAL", message=message)`
- `LLMCallFailedError` → 继承 `TransientError`，无需改
- `SummarizationEmpty` → 无 `__init__`，需添加：`def __init__(self) -> None: super().__init__(code="MEMORY_SUMMARY_EMPTY", message="LLM returned empty content")`
- `ConfigError` → 继承 `FatalError`，无需改
- `IndexIntegrityError` → 继承 `FatalError`，无需改

- [ ] **步骤 2：运行 memory 测试验证**

```bash
uv run pytest tests/memory/ -v
```

- [ ] **步骤 3：运行检查 + commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
git add app/memory/exceptions.py && git commit -m "refactor: MemoryBankError extends AppError"
```

---

### 任务 4：Models 异常迁移

**文件：**
- 修改：`app/models/chat.py`

- [ ] **步骤 1：修改 `ChatError` 层级继承 `AppError`**

在 `app/models/chat.py` 中：
1. 添加 `from app.exceptions import AppError`
2. 将 `ChatError` 基类从 `Exception` 改为 `AppError`

先验证直接实例化：
```bash
rg "ChatError\(" app/ tests/ --type py | grep -v "class " | grep -v "import"
```

具体改动——`ChatError` 当前是基类（可能无 `__init__`），需查看实际签名。所有子类补充 `code`：

| 异常类 | code 值 |
|--------|---------|
| `ChatError`（基类） | `"MODEL_ERROR"` |
| `NoProviderError` | `"MODEL_NO_PROVIDER"` |
| `AllProviderFailedError` | `"MODEL_ALL_FAILED"` |
| `NoLLMConfigurationError` | `"MODEL_NO_CONFIG"` |
| `MissingModelFieldError` | `"MODEL_MISSING_FIELD"` |
| `NoDefaultModelGroupError` | `"MODEL_NO_DEFAULT_GROUP"` |
| `NoJudgeModelConfiguredError` | `"MODEL_NO_JUDGE"` |

每个子类 `__init__` 中将 `super().__init__(message)` 改为 `super().__init__(code="MODEL_...", message=message)`。基类 `ChatError` 若无 `__init__`，需添加：
```python
def __init__(self, code: str = "MODEL_ERROR", message: str = "") -> None:
    super().__init__(code=code, message=message)
```

- [ ] **步骤 2：运行 models 测试**

```bash
uv run pytest tests/models/ -v
```

- [ ] **步骤 3：检查 + commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
git add app/models/chat.py && git commit -m "refactor: ChatError extends AppError"
```

---

### 任务 5：Tools 异常迁移

**文件：**
- 修改：`app/tools/executor.py`

- [ ] **步骤 1：`ToolExecutionError` 继承 `AppError`**

```python
from app.exceptions import AppError

class ToolExecutionError(AppError):
    """工具执行异常。"""

    def __init__(self, message: str) -> None:
        super().__init__(code="TOOL_ERROR", message=message)
```

- [ ] **步骤 2：运行 tools 测试**

```bash
uv run pytest tests/tools/ -v
```

- [ ] **步骤 3：检查 + commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
git add app/tools/executor.py && git commit -m "refactor: ToolExecutionError extends AppError"
```

---

### 任务 6：Workflow 异常迁移

**文件：**
- 修改：`app/agents/workflow.py`

- [ ] **步骤 1：替换 `ChatModelUnavailableError` 为 `WorkflowError(AppError)`**

```python
# 删除原 ChatModelUnavailableError(RuntimeError) 定义（第 65-70 行）
# 替换为：
from app.exceptions import AppError

class WorkflowError(AppError):
    """工作流异常（模型不可用等）。"""

    def __init__(self, code: str = "WORKFLOW_ERROR", message: str = "") -> None:
        if not message:
            message = "Workflow error"
        super().__init__(code=code, message=message)
```

全局搜索替换 `ChatModelUnavailableError` → `WorkflowError`，所有引用处同步更新：
- `workflow.py:366` — `raise ChatModelUnavailableError` → `raise WorkflowError(code="MODEL_UNAVAILABLE", message="ChatModel not available")`

- [ ] **步骤 2：运行 agents 测试**

```bash
uv run pytest tests/agents/ -v
```

- [ ] **步骤 3：检查 + commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
git add app/agents/workflow.py && git commit -m "refactor: replace ChatModelUnavailableError with WorkflowError(AppError)"
```

---

## 阶段三：API 层统一异常边界

### 任务 7：`safe_call()` 替代 `safe_memory_call()` + API AppError 多重继承

**文件：**
- 修改：`app/api/errors.py`

- [ ] **步骤 1：API `AppError` 改为多重继承 `AppError + HTTPException`**

API 层现有 `class AppError(HTTPException)` 改为 `class AppError(BaseAppError, HTTPException)`，同时兼容异常体系基类和 FastAPI 异常处理。

```python
# app/api/errors.py
from app.exceptions import AppError as BaseAppError

class AppError(BaseAppError, HTTPException):
    """API 异常——同时是 BaseAppError 和 HTTPException。

    isinstance(err, BaseAppError) → True（safe_call 可 catch）
    isinstance(err, HTTPException) → True（FastAPI exception handler 可 catch）
    """

    def __init__(
        self,
        code: AppErrorCode,
        message: str,
        status_code: int | None = None,
    ) -> None:
        self.app_message = message
        resolved = (
            status_code if status_code is not None else _CODE_TO_HTTP.get(code, 500)
        )
        # BaseAppError.__init__ 设置 code/message
        BaseAppError.__init__(self, code=code.value, message=message)
        # HTTPException.__init__ 设置 status_code/detail
        HTTPException.__init__(self, status_code=resolved, detail=message)
```

所有 API 端点中 `from app.api.errors import AppError` 不变，`raise AppError(AppErrorCode.XXX, "msg")` 不变。

- [ ] **步骤 2：实现 `safe_call()`**

```python
from app.memory.exceptions import MemoryBankError, TransientError, FatalError
from app.tools.executor import ToolExecutionError

async def safe_call[T](
    coro: Awaitable[T],
    context_msg: str,
) -> T:
    """执行异步调用，异常统一转为 AppError（HTTP 子类）。

    BaseAppError 子类（含 API AppError）→ 直接 raise
    TransientError → 503
    FatalError → 500
    ToolExecutionError → 500
    ValueError → 422
    OSError → 503
    其余 → 500
    """
    try:
        return await coro
    except BaseAppError:
        # 已是 AppError 体系（含 API AppError），直接透传
        raise
    except TransientError as e:
        logger.exception("%s: transient error", context_msg)
        raise AppError(AppErrorCode.STORAGE_ERROR, "Service temporarily unavailable") from e
    except FatalError as e:
        logger.exception("%s: fatal error", context_msg)
        raise AppError(AppErrorCode.INTERNAL_ERROR, "Internal storage error") from e
    except ToolExecutionError as e:
        logger.exception("%s: tool error", context_msg)
        raise AppError(AppErrorCode.INTERNAL_ERROR, "Tool execution failed") from e
    except OSError as e:
        logger.exception("%s: IO error", context_msg)
        raise AppError(AppErrorCode.STORAGE_ERROR, "Service temporarily unavailable") from e
    except ValueError as e:
        logger.exception("%s: validation error", context_msg)
        raise AppError(AppErrorCode.INVALID_INPUT, "Invalid request data") from e
    except Exception as e:
        logger.exception("%s: unexpected error", context_msg)
        raise AppError(AppErrorCode.INTERNAL_ERROR, "Internal server error") from e
```

保留 `safe_memory_call` 为 `safe_call` 的别名（向后兼容）：
```python
safe_memory_call = safe_call
```

- [ ] **步骤 2：检查 + commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
git add app/api/errors.py && git commit -m "feat: add safe_call() with AppError-aware mapping"
```

---

### 任务 8：API 端点迁移到 `safe_call()`

**文件：**
- 修改：`app/api/v1/query.py`
- 修改：`app/api/v1/feedback.py`
- 修改：`app/api/v1/data.py`
- 修改：`app/api/v1/reminders.py`（也使用 `get_memory_module()` 裸 except）
- 修改：`app/api/v1/presets.py`（也使用存储操作）

- [ ] **步骤 1：`query.py` 迁移**

将裸 `try/except Exception` + `raise AppError(INTERNAL_ERROR)` 替换为 `safe_call()`。

当前模式（需替换）：
```python
try:
    memory_module = get_memory_module()
except Exception:
    raise AppError(AppErrorCode.INTERNAL_ERROR, "Memory module unavailable")
```

替换为：
```python
from app.api.errors import safe_call

# 在 process_query 函数内，将 get_memory_module() 调用包装在 safe_call 中
memory_module = await safe_call(
    asyncio.to_thread(get_memory_module),
    "get_memory_module",
)
```

注意：`get_memory_module()` 是同步函数，需 `asyncio.to_thread()` 包装，或在 `safe_call` 外先调用。查看原代码确认调用方式——若原代码已在 async 函数内直接调用同步 `get_memory_module()`，则保持原方式但用 `safe_call` 包裹后续异步操作。

具体改动：将 `query.py` 中涉及 memory/workflow 操作的裸 except 替换为 `safe_call()` 包裹。

- [ ] **步骤 2：`feedback.py` 迁移**

同样模式替换。

- [ ] **步骤 3：`data.py` 迁移**

同样模式替换。

- [ ] **步骤 4：`reminders.py` 和 `presets.py` 迁移**

检查这两个文件中的裸 `try/except Exception` 模式，同样替换为 `safe_call()` 包裹。

- [ ] **步骤 5：运行 API 测试**

```bash
uv run pytest tests/api/ -v
```

- [ ] **步骤 6：检查 + commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
git add app/api/ && git commit -m "refactor: migrate API endpoints to safe_call()"
```

---

## 阶段四：Workflow 拆分

### 任务 9：删除弃用代码 + `_haversine` 统一

**文件：**
- 修改：`app/agents/workflow.py`
- 修改：`app/agents/pending.py`
- 修改：`app/scheduler/context_monitor.py`

- [ ] **步骤 1：确认 `TaskOutput` 无外部导入**

```bash
rg "TaskOutput" app/ tests/ --type py
rg "StrategyOutput" app/ tests/ --type py
```

若仅在 `workflow.py` 内定义且无外部导入，则安全删除。

- [ ] **步骤 2：删除 `TaskOutput`（约 128-156 行）和 `StrategyOutput`（约 158-181 行）**

从 `workflow.py` 删除两个弃用 Pydantic 模型类。

- [ ] **步骤 3：`pending.py` 删除 `_haversine`，改导入**

```python
# 删除 pending.py 中的 _haversine 函数
# 添加导入：
from app.utils import haversine

# 所有 PendingReminderManager._haversine(...) 调用改为 haversine(...)
```

`_haversine` 在 `pending.py` 中是 `@staticmethod`，调用方式为 `PendingReminderManager._haversine(...)` 。改为 `haversine(...)` 后去掉类前缀。

- [ ] **步骤 4：`context_monitor.py` 删除 `_haversine`，改导入**

```python
# 删除 context_monitor.py 中的 _haversine 函数
# 添加导入：
from app.utils import haversine

# _haversine(...) → haversine(...)
```

- [ ] **步骤 5：运行全量测试**

```bash
uv run pytest -v
```

- [ ] **步骤 6：检查 + commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
git add -A && git commit -m "refactor: remove deprecated models, unify haversine"
```

---

### 任务 10：`apply_rules()` 缓存

**文件：**
- 修改：`app/agents/workflow.py`

- [ ] **步骤 1：`_format_constraints_hint()` 接受 `rules_result` 参数**

将签名从 `(driving_context: dict | None)` 改为 `(rules_result: dict)`，移除内部 `apply_rules()` 调用。

```python
@staticmethod
def _format_constraints_hint(rules_result: dict) -> str:
    """rules_result → 自然语言约束提示。"""
    hints: list[str] = []
    channels = rules_result.get("allowed_channels")
    if channels:
        ch_str = ", ".join(channels)
        hints.append(f"当前仅建议通过 {ch_str} 通道提醒。")
    max_freq = rules_result.get("max_frequency_minutes")
    if max_freq is not None:
        hints.append(f"两次提醒建议至少间隔 {max_freq} 分钟。")
    if rules_result.get("only_urgent"):
        hints.append("当前仅紧急提醒适合发送。")
    if rules_result.get("postpone"):
        hints.append("当前应延后非紧急提醒。")
    return " ".join(hints)
```

- [ ] **步骤 2：在 `_joint_decision_node()` 首次计算 rules，存入 state**

在 `_joint_decision_node()` 中（当前约 475-560 行），首次调用 `apply_rules(driving_ctx)` 后将结果存入 `state["rules_result"]`。

思路：
```python
# 在 _joint_decision_node 内，计算 constraints_hint 之前：
driving_ctx = state.get("driving_context")
rules_result = apply_rules(driving_ctx) if driving_ctx else {}
state["rules_result"] = rules_result
constraints_hint = self._format_constraints_hint(rules_result)
```

- [ ] **步骤 3：`_check_frequency_guard()` 从 state 读取 rules**

```python
async def _check_frequency_guard(self, state: AgentState) -> str | None:
    driving_ctx = state.get("driving_context")
    if not driving_ctx:
        return None
    rules_result = state.get("rules_result") or apply_rules(driving_ctx)
    max_freq = rules_result.get("max_frequency_minutes")
    ...
```

- [ ] **步骤 4：`_execution_node()` 各处 `apply_rules()` 改为读 `state["rules_result"]`**

在 `_execution_node()` 中，第 669-671 行和第 752-754 行的 `apply_rules(driving_ctx)` 调用替换为：
```python
rules_result = state.get("rules_result") or (apply_rules(driving_ctx) if driving_ctx else {})
```

- [ ] **步骤 5：`run_with_stages` / `proactive_run` / `run_stream` 中同步更新**

`proactive_run()` 中 `constraints_hint = self._format_constraints_hint(context_override)` 需改为先计算 rules_result 再传参。

- [ ] **步骤 6：运行 agents 测试**

```bash
uv run pytest tests/agents/ -v
```

- [ ] **步骤 7：检查 + commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
git add app/agents/workflow.py && git commit -m "refactor: cache apply_rules() result in state"
```

---

### 任务 11：拆分 `_execution_node()`

**文件：**
- 修改：`app/agents/workflow.py`

- [ ] **步骤 1：提取 `_handle_cancel()`**

将 595-616 行提取为独立方法：

```python
async def _handle_cancel(self, state: AgentState, stages: WorkflowStages | None) -> dict:
    """处理 cancel_last action。"""
    pm = PendingReminderManager(user_data_dir(self.current_user))
    cancelled = await pm.cancel_last()
    result = "提醒已取消" if cancelled else "暂无待取消的提醒"
    if stages is not None:
        stages.execution = {
            "content": None,
            "event_id": None,
            "result": result,
            "cancelled": cancelled,
        }
    return {
        "result": result,
        "event_id": None,
        "action_result": {"cancelled": cancelled},
    }
```

- [ ] **步骤 2：提取 `_handle_tool_calls()`**

将 646-661 行提取为独立方法：

```python
async def _handle_tool_calls(self, decision: dict) -> None:
    """执行工具调用，结果仅 log。"""
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
            except Exception as e:
                tool_results.append(f"[{t_name}] 失败: {e}")
    if tool_results:
        logger.info("Tool call results: %s", "; ".join(tool_results))
```

- [ ] **步骤 3：提取 `_handle_postpone()`**

将 663-733 行（postpone/delay/location → PendingReminder）提取为独立方法。含 `_map_pending_trigger` 调用、location_time 拆分逻辑。

思路：方法签名 `_handle_postpone(self, decision: dict, state: AgentState, driving_ctx: dict | None, rules_result: dict, modifications: list[str], stages: WorkflowStages | None) -> dict`

- [ ] **步骤 4：提取 `_handle_immediate_send()`**

将 747-788 行（即时发送：内容提取 + OutputRouter + 隐私脱敏 + Memory 写入）提取为独立方法。

思路：方法签名 `_handle_immediate_send(self, decision: dict, state: AgentState, driving_ctx: dict | None, rules_result: dict, modifications: list[str], stages: WorkflowStages | None) -> dict`

- [ ] **步骤 5：重构 `_execution_node()` 为路由方法**

```python
async def _execution_node(self, state: AgentState) -> dict:
    decision = state.get("decision") or {}
    stages = state.get("stages")

    # 快捷指令 action
    action = decision.get("action", "")
    if action == "cancel_last":
        return await self._handle_cancel(state, stages)

    # 规则硬约束
    driving_ctx = state.get("driving_context")
    modifications: list[str] = []
    if driving_ctx and not decision.get("_postprocessed"):
        decision, modifications = postprocess_decision(decision, driving_ctx)

    if stages is not None:
        stages.decision = decision

    if not decision.get("should_remind", True):
        result = "提醒已取消：安全规则禁止发送"
        if stages is not None:
            stages.execution = {"content": None, "event_id": None, "result": result, "modifications": modifications}
        return {"result": result, "event_id": None}

    # 工具调用
    await self._handle_tool_calls(decision)

    rules_result = state.get("rules_result") or (apply_rules(driving_ctx) if driving_ctx else {})

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

- [ ] **步骤 6：运行全量测试**

```bash
uv run pytest -v
```

- [ ] **步骤 7：检查 + commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
git add app/agents/workflow.py && git commit -m "refactor: split _execution_node into sub-methods"
```

---

## 阶段五：异常 catch 清理

### 任务 12：宽泛异常清单替换

**文件：**
- 修改：`app/agents/workflow.py`
- 修改：`app/scheduler/scheduler.py`

- [ ] **步骤 1：`workflow.py` 中宽泛 catch 改为 `AppError`**

将以下位置替换：
- `_safe_memory_search()` 第 382 行：`except (OSError, ValueError, RuntimeError, TypeError, KeyError) as e:` → `except AppError as e:`
- `_safe_memory_history()` 第 394 行：同上

**注意**：Memory 模块异常已继承 `AppError`（任务 3），Memory 操作内部抛出的 `MemoryBankError` 子类会被 `except AppError` 捕获。Memory 操作不会抛裸 `OSError`/`ValueError`（已在其内部被捕获转为 `MemoryBankError` 子类）。若仍有外部库直接抛标准异常的路径，这些异常由 `run_with_stages` 顶层 `except Exception` 兜底——这是正确的最终边界，保持不变。

添加 `from app.exceptions import AppError` 导入。

- [ ] **步骤 2：`scheduler.py` 中宽泛 catch 改为 `AppError`**

将以下位置替换：
- `_poll_pending()` 第 121 行：`except (OSError, RuntimeError, ValueError, TypeError) as e:` → `except AppError as e:`
- `_evaluate_and_execute()` 第 230 行：同上
- `_drain_voice_queue()` 第 250 行：同上

**注意**：与 workflow 同理，底层模块异常已继承 `AppError`。`_tick()` 和 `run()` 中的 `except Exception` 兜底保持不变。

添加 `from app.exceptions import AppError` 导入。

- [ ] **步骤 3：运行全量测试**

```bash
uv run pytest -v
```

- [ ] **步骤 4：检查 + commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
git add -A && git commit -m "refactor: replace broad exception lists with AppError catch"
```

---

## 阶段六：配置接线 + 基础设施修复

### 任务 13：`scheduler.toml` 配置接线

**文件：**
- 修改：`app/scheduler/scheduler.py`

- [ ] **步骤 1：读取 `enable_periodic_review` 和 `review_time`**

在 `__init__` 中，从 `_cfg` 读取：

```python
self._enable_periodic_review: bool = _cfg.get("enable_periodic_review", True)
self._review_time: str = _cfg.get("review_time", "08:00")
```

- [ ] **步骤 2：解析 `review_time` 为小时和分钟**

```python
# 在 __init__ 中解析
try:
    parts = self._review_time.split(":")
    self._review_hour = int(parts[0])
    self._review_minute = int(parts[1]) if len(parts) > 1 else 0
except (ValueError, IndexError):
    logger.warning("Invalid review_time format: %s, using default 08:00", self._review_time)
    self._review_hour = 8
    self._review_minute = 0
```

- [ ] **步骤 3：在 `_build_signals()` 中使用实例变量替代硬编码**

将第 175-185 行的 `_REVIEW_HOUR` / `_REVIEW_WINDOW_MINUTES` 替换为 `self._review_hour` / `self._review_minute` + `self._enable_periodic_review` 守卫：

```python
if self._enable_periodic_review:
    now_local = datetime.now().astimezone()
    today_str = now_local.strftime("%Y-%m-%d")
    if (
        now_local.hour == self._review_hour
        and now_local.minute == self._review_minute
        and self._last_review_date != today_str
    ):
        self._last_review_date = today_str
        signals.append(TriggerSignal(source="periodic", priority=0, context=ctx_copy))
```

注意：同时修复 UTC 时区问题，改用 `datetime.now().astimezone()` 取本地时间。

- [ ] **步骤 4：删除硬编码常量**

删除第 28-29 行的 `_REVIEW_HOUR = 8` 和 `_REVIEW_WINDOW_MINUTES = 5`。

- [ ] **步骤 5：检查 + commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
git add app/scheduler/scheduler.py && git commit -m "fix: wire scheduler.toml review config, use local timezone"
```

---

### 任务 14：`tools.toml` enabled 接线

**文件：**
- 修改：`app/tools/tools/__init__.py`

- [ ] **步骤 1：`register_builtin_tools()` 读取 enabled 字段**

在注册每个工具前读取 `config/tools.toml`，检查 `enabled` 字段：

思路：
```python
import tomllib
from pathlib import Path

def register_builtin_tools(registry: ToolRegistry) -> None:
    """注册内置工具，按 tools.toml 的 enabled 字段过滤。"""
    config_path = Path("config/tools.toml")
    try:
        with config_path.open("rb") as f:
            config = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        config = {}

    tools_config = config.get("tools", {})

    def is_enabled(tool_name: str) -> bool:
        return tools_config.get(tool_name, {}).get("enabled", True)

    if is_enabled("navigation"):
        registry.register(ToolSpec(...))
    if is_enabled("communication"):
        registry.register(ToolSpec(...))
    # ... 以此类推
```

- [ ] **步骤 2：运行 tools 测试**

```bash
uv run pytest tests/tools/ -v
```

- [ ] **步骤 3：检查 + commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
git add app/tools/tools/__init__.py && git commit -m "fix: wire tools.toml enabled field"
```

---

### 任务 15：`voice.toml` 统一加载 + `_FRAME_BYTES` 清理

**文件：**
- 修改：`app/voice/pipeline.py`
- 修改：`app/voice/vad.py`
- 修改：`app/voice/asr.py`
- 修改：`app/voice/constants.py`

- [ ] **步骤 1：`VoicePipeline.__init__()` 统一加载 `voice.toml`**

在 `pipeline.py` 中，将 `_load_voice_config()` 和 `_load_asr_config()` 合并为一次加载，结果传递给 `VADEngine` 和 `SherpaOnnxASREngine` 构造函数。

思路：
```python
class VoicePipeline:
    def __init__(self, on_transcription=None):
        config = self._load_config()  # 一次加载 voice.toml
        self._min_confidence = config.get("min_confidence", 0.5)
        vad_config = config  # voice 段
        asr_config = config.get("asr", {})
        self._vad = VADEngine(
            vad_mode=vad_config.get("vad_mode", 1),
            sample_rate=vad_config.get("sample_rate", 16000),
            silence_timeout_ms=vad_config.get("silence_timeout_ms", 500),
        )
        self._asr = SherpaOnnxASREngine(config=asr_config)
        self._expected_frame_bytes = self._vad.frame_bytes  # 从实例读
        ...
```

- [ ] **步骤 2：`VADEngine` 暴露 `frame_bytes` 属性**

```python
class VADEngine:
    @property
    def frame_bytes(self) -> int:
        return self._frame_bytes
```

- [ ] **步骤 3：`constants.py` 删除 `_FRAME_BYTES`**

删除 `_FRAME_BYTES = 960`。`pipeline.py` 中对 `constants._FRAME_BYTES` 的引用改为 `self._expected_frame_bytes`。

- [ ] **步骤 4：`ASREngine` 接受 config dict 参数**

`SherpaOnnxASREngine.__init__()` 改为接受 `config: dict` 参数，不再自己加载 `voice.toml`。

- [ ] **步骤 5：运行 voice 测试**

```bash
uv run pytest tests/voice/ -v
```

- [ ] **步骤 6：检查 + commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
git add app/voice/ && git commit -m "refactor: unify voice.toml loading, remove _FRAME_BYTES"
```

---

### 任务 16：时区修复

**文件：**
- 修改：`app/agents/pending.py`

- [ ] **步骤 1：`parse_time()` 返回带 tzinfo 的 datetime**

当前返回 `f"{today}T{hour:02d}:00:00"` 字符串无时区。改为返回 `datetime` 对象：

```python
from datetime import UTC, datetime

def parse_time(text: str) -> datetime | None:
    """解析时间表达为带 tzinfo 的 datetime。"""
    # ... 原有解析逻辑 ...
    today = datetime.now(UTC).date()
    target = datetime(today.year, today.month, today.day, hour, 0, 0, tzinfo=UTC)
    return target
```

调用方需同步更新：`_map_pending_trigger()` 中使用 `parse_time()` 的地方，将 `trigger_target` 中的 time 值改为 datetime 对象的 ISO 格式（自动含 tzinfo）。

- [ ] **步骤 2：`_check_time()` 简化**

因 target_time 已含 tzinfo，删除手动 `replace(tzinfo=UTC)` 行。

- [ ] **步骤 3：运行 pending 测试**

```bash
uv run pytest tests/agents/test_pending.py -v
```

- [ ] **步骤 4：检查 + commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
git add app/agents/pending.py && git commit -m "fix: parse_time returns tz-aware datetime"
```

---

### 任务 17：`_PER_USER_LOCKS` 改 WeakValueDictionary

**文件：**
- 修改：`app/agents/pending.py`

- [ ] **步骤 1：替换 dict 为 WeakValueDictionary**

```python
from weakref import WeakValueDictionary

_PER_USER_LOCKS: WeakValueDictionary[Path, asyncio.Lock] = WeakValueDictionary()
```

行为：当 `PendingReminderManager` 实例被 GC 回收后，其持有的 Lock 引用消失，WeakValueDictionary 自动清理对应条目。

- [ ] **步骤 2：运行 pending 测试**

```bash
uv run pytest tests/agents/test_pending.py -v
```

- [ ] **步骤 3：检查 + commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
git add app/agents/pending.py && git commit -m "refactor: _PER_USER_LOCKS use WeakValueDictionary"
```

---

### 任务 18：杂项修复

**文件：**
- 修改：`app/agents/probabilistic.py`
- 修改：`app/tools/tools/communication.py`
- 修改：`app/storage/jsonl_store.py`
- 修改：`app/storage/experiment_store.py`

- [ ] **步骤 1：`compute_interrupt_risk()` key 统一**

`probabilistic.py` 中 `driving_context.get("driver", {})` 统一为 `driving_context.get("driver_state", {})`，与 `ContextOutput.driver_state` 字段名及 `context_monitor.py` 中的 `driver_state` 保持一致。

或者反向统一：将所有 `driver_state` 改为 `driver`。需检查哪种更少改动。

建议：保持 `driver_state` 不变（ContextOutput Pydantic 模型、context_monitor.py、scheduler.py 中 `_build_signals` 均使用 `driver_state`），将 `probabilistic.py` 中 `ctx.get("driver", {})` 改为 `ctx.get("driver_state", {})`。

- [ ] **步骤 2：`communication.py` 配置缓存**

```python
_message_max_length: int | None = None

def _load_message_max_length() -> int:
    global _message_max_length
    if _message_max_length is not None:
        return _message_max_length
    # ... 原有加载逻辑 ...
    _message_max_length = length
    return _message_max_length
```

- [ ] **步骤 3：`jsonl_store.py` mkdir 移到 `__init__`**

将 `self.filepath.parent.mkdir(parents=True, exist_ok=True)` 从 `append()` 移到 `__init__()`。`append()` 中删除此行。

- [ ] **步骤 4：`experiment_store.py` 改 aiofiles**

```python
import aiofiles
import tomllib

async def read_benchmark() -> dict:
    """异步读取实验 benchmark 数据。"""
    path = Path("data/experiment_benchmark.toml")
    if not await asyncio.to_thread(path.exists):
        return {}
    async with aiofiles.open(path, "rb") as f:
        content = await f.read()
    # tomllib.loads 接受 str，aiofiles rb 模式返回 bytes
    return tomllib.loads(content.decode("utf-8"))
```

- [ ] **步骤 5：运行全量测试**

```bash
uv run pytest -v
```

- [ ] **步骤 6：检查 + commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
git add -A && git commit -m "fix: misc infra fixes (key unify, config cache, async store)"
```

---

## 阶段七：测试覆盖补全

### 任务 19：Scheduler 全面测试

**文件：**
- 新建：`tests/scheduler/test_tick.py`

- [ ] **步骤 1：编写 `_tick()` 流程测试**

```python
"""Scheduler tick 完整流程测试。"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.scheduler.scheduler import ProactiveScheduler
from app.scheduler.context_monitor import ContextDelta


@pytest.fixture
def mock_workflow():
    wf = MagicMock()
    wf.current_user = "default"
    wf.memory_module = MagicMock()
    wf.proactive_run = AsyncMock(return_value=("result", None, MagicMock()))
    return wf


@pytest.fixture
def mock_memory():
    return MagicMock()


@pytest.fixture
def scheduler(mock_workflow, mock_memory):
    return ProactiveScheduler(
        workflow=mock_workflow,
        memory_module=mock_memory,
        tick_interval=1,
        debounce_seconds=0,
    )
```

测试用例：

1. `_drain_voice_queue` 正常写入 — `Given queue 有文本, When _tick, Then memory_module.write 被调用`
2. `_drain_voice_queue` 空文本跳过 — `Given queue 有空字符串, When _tick, Then write 不被调用`
3. `_drain_voice_queue` 写入失败降级 — `Given write 抛异常, When _tick, Then 不崩溃`
4. `_poll_pending` 触发 — `Given pending reminder 满足条件, When _tick, Then proactive_run 被调用`
5. `_poll_pending` 执行失败降级 — `Given proactive_run 抛异常, When _tick, Then 不崩溃`
6. `_build_signals` scenario 变化 — `Given delta.scenario_changed, When _build_signals, Then 含 context_change 信号`
7. `_build_signals` location 变化 — `Given delta.location_changed, When _build_signals, Then 含 location 信号`
8. `_build_signals` state 变化 — `Given delta.fatigue_increased, When _build_signals, Then 含 state 信号`
9. `_build_signals` periodic 触发 — `Given 时间窗口匹配, When _build_signals, Then 含 periodic 信号`
10. `_evaluate_and_execute` 触发后 WS 广播 — `Given should_trigger, When evaluate_and_execute, Then ws_manager.broadcast 被调用`

- [ ] **步骤 2：运行测试**

```bash
uv run pytest tests/scheduler/test_tick.py -v
```

- [ ] **步骤 3：检查 + commit**

```bash
uv run ruff check --fix && uv run ruff format
git add tests/scheduler/test_tick.py && git commit -m "test: add scheduler tick coverage"
```

---

### 任务 20：Tools Executor 测试

**文件：**
- 新建：`tests/tools/test_executor.py`

- [ ] **步骤 1：编写 executor 测试**

```python
"""ToolExecutor 全面测试。"""
from unittest.mock import AsyncMock
import pytest
from app.tools.executor import ToolExecutionError, ToolExecutor
from app.tools.registry import ToolRegistry, ToolSpec
```

测试用例：

1. 未知工具 → `ToolExecutionError` — `Given 注册表中无该工具, When execute, Then raise ToolExecutionError`
2. 缺 required 参数 → `ToolExecutionError` — `Given 缺 required 字段, When execute, Then raise`
3. 类型错误 → `ToolExecutionError` — `Given int 字段传 str, When execute, Then raise`
4. minimum 约束违反 → `ToolExecutionError`
5. maxLength 约束违反 → `ToolExecutionError`
6. enum 约束违反 → `ToolExecutionError`
7. handler 异常 → `ToolExecutionError`（`raise X from Y`）
8. 正常执行返回结果

- [ ] **步骤 2：运行测试**

```bash
uv run pytest tests/tools/test_executor.py -v
```

- [ ] **步骤 3：检查 + commit**

```bash
uv run ruff check --fix && uv run ruff format
git add tests/tools/test_executor.py && git commit -m "test: add tool executor coverage"
```

---

### 任务 21：Voice Pipeline 测试

**文件：**
- 新建：`tests/voice/test_pipeline.py`

- [ ] **步骤 1：编写 pipeline 测试**

```python
"""VoicePipeline 测试。"""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
```

测试用例：

1. 正常 VAD → ASR 流水线 — `Given 语音帧 → VAD speech_end, When run, Then ASR.transcribe 被调用, yield text`
2. 置信度过滤 — `Given ASR confidence < min_confidence, When run, Then 不 yield`
3. ASR 不可用 → 空文本 — `Given _recognizer is _UNAVAILABLE, When transcribe, Then 返回空 ASRResult`
4. 帧大小不匹配 → 跳过 — `Given 错误大小帧, When run, Then warning + skip`
5. 回调触发 — `Given on_transcription callback, When yield text, Then callback 被调用`

- [ ] **步骤 2：运行测试**

```bash
uv run pytest tests/voice/test_pipeline.py -v
```

- [ ] **步骤 3：检查 + commit**

```bash
uv run ruff check --fix && uv run ruff format
git add tests/voice/test_pipeline.py && git commit -m "test: add voice pipeline coverage"
```

---

## 阶段八：最终验证

### 任务 22：全量验证

- [ ] **步骤 1：运行全量测试**

```bash
uv run pytest -v
```

预期：全部通过，测试数 ≥ 545（原 521 + 新增 ~24）

- [ ] **步骤 2：运行 lint + type check**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```

预期：零错误

- [ ] **步骤 3：最终 commit**

```bash
git add -A && git commit -m "chore: final validation pass"
```
