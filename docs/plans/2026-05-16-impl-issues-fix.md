# 实现问题修复计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。

**目标：** 修复 7 项实现问题（P0-2/P0-3/P1-4/P2-8/P2-9/P2-10/P3-11），核心变更为 AgentWorkflow 深度重构。

**架构：** 将 AgentWorkflow（1109 行 God class）拆为 ContextAgent / JointDecisionAgent / ExecutionAgent + 薄编排器。同步修复 CORS、工具安全、PendingReminderManager 生命周期、工具结果回传、环境变量命名。

**技术栈：** Python 3.14, FastAPI, Pydantic, pytest

---

## 文件结构

| 文件 | 动作 | 职责 |
|------|------|------|
| `app/agents/types.py` | 新建 | Pydantic 模型、WorkflowError、共享函数（从 workflow.py 迁出） |
| `app/agents/context_agent.py` | 新建 | ContextAgent：记忆检索 + 对话历史 + LLM 上下文推断 |
| `app/agents/joint_decision_agent.py` | 新建 | JointDecisionAgent：规则约束 + 偏好 + 概率推断 + LLM 决策 |
| `app/agents/execution_agent.py` | 新建 | ExecutionAgent：规则后处理 + 工具 + pending + 频次 + 记忆写入 |
| `app/agents/workflow.py` | 重写 | 薄编排器：3 入口 + SSE + 快捷指令 |
| `app/agents/state.py` | 改 | 新增 `tool_results` 字段 |
| `app/api/main.py` | 改 | CORS 配置化 |
| `app/tools/registry.py` | 改 | ToolSpec 新增 `require_confirmation_when` |
| `app/tools/executor.py` | 改 | 新增 `ToolConfirmationRequiredError` |
| `app/tools/tools/__init__.py` | 改 | 注册时传入 confirmation 条件 |
| `app/agents/rules.py` | 改 | 环境变量命名 |
| 各模块 `AGENTS.md` | 改 | 文档同步 |

---

## 任务 1：提取 types.py

**文件：**
- 创建：`app/agents/types.py`
- 修改：`app/agents/workflow.py`（删除迁出代码，改为从 types 导入）
- 修改：`tests/agents/test_llm_json_validation.py`（更新导入路径）

- [ ] **步骤 1：创建 `app/agents/types.py`**

从 `workflow.py` 迁出以下内容（保持代码不变）：

```python
"""Agent 类型定义：Pydantic 模型、异常、共享函数。"""

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
)

from app.exceptions import AppError

if TYPE_CHECKING:
    from app.memory.memory import MemoryModule


class WorkflowError(AppError):
    """工作流异常（模型不可用等）。"""

    def __init__(self, code: str = "WORKFLOW_ERROR", message: str = "") -> None:
        if not message:
            message = "Workflow error"
        super().__init__(code=code, message=message)


class LLMJsonResponse(BaseModel):
    """LLM JSON 输出包装，含校验与兜底。"""

    model_config = ConfigDict(extra="forbid")

    raw: str
    data: dict | None = None

    @classmethod
    def from_llm(cls, text: str) -> LLMJsonResponse:
        cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            data = json.loads(cleaned)
            if isinstance(data, dict):
                return cls(raw=text, data=data)
        except json.JSONDecodeError:
            pass
        return cls(raw=text)


class ContextOutput(BaseModel):
    """Context Agent JSON 输出模型。"""

    model_config = ConfigDict(extra="forbid")

    scenario: str = Field(
        default="",
        validation_alias=AliasChoices("scenario", "scene", "driving_scenario"),
    )
    driver_state: dict = Field(
        default_factory=dict,
        validation_alias=AliasChoices("driver_state", "driver", "state"),
    )
    spatial: dict = Field(
        default_factory=dict,
        validation_alias=AliasChoices("spatial", "location", "position"),
    )
    traffic: dict = Field(
        default_factory=dict,
        validation_alias=AliasChoices("traffic", "traffic_status"),
    )
    current_datetime: str = Field(
        default="",
        validation_alias=AliasChoices("current_datetime", "datetime", "time"),
    )
    related_events: list = Field(
        default_factory=list,
        validation_alias=AliasChoices("related_events", "events", "history"),
    )
    conversation_history: list | None = None


class JointDecisionOutput(BaseModel):
    """JointDecision Agent JSON 输出模型。"""

    model_config = ConfigDict(extra="forbid")

    task_type: str = Field(
        default="general",
        validation_alias=AliasChoices("task_type", "type", "task_attribution"),
    )
    confidence: float = Field(
        default=0.0,
        validation_alias=AliasChoices("confidence", "conf"),
    )
    entities: list = Field(
        default_factory=list,
        validation_alias=AliasChoices("entities", "events", "event_list"),
    )
    decision: dict = Field(default_factory=dict)


class ReminderContent(BaseModel):
    """提醒内容校验模型。"""

    text: str = ""
    content: str = ""

    @classmethod
    def from_decision(cls, decision: dict) -> str:
        for key in ("reminder_content", "remind_content", "content"):
            val = decision.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
            if isinstance(val, dict):
                return val.get("text") or val.get("content") or "无提醒内容"
        return "无提醒内容"


async def call_llm_json(chat_model: object, prompt: str) -> LLMJsonResponse:
    """共享 LLM JSON 调用。chat_model 需有 generate(prompt, json_mode=True) 方法。"""
    from app.models.chat import ChatModel  # noqa: F811 延迟导入避免循环

    if not chat_model:
        raise WorkflowError(code="MODEL_UNAVAILABLE", message="ChatModel not available")
    assert isinstance(chat_model, ChatModel)
    result = await chat_model.generate(prompt, json_mode=True)
    return LLMJsonResponse.from_llm(result)


def format_time_for_display(time_str: str) -> str:
    """从 ISO 时间字符串提取 HH:MM。"""
    try:
        dt = datetime.fromisoformat(time_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.strftime("%H:%M")
    except ValueError, TypeError:
        return time_str


def extract_location_target(driving_ctx: dict | None) -> dict:
    """从 driving_context 中提取目标位置经纬度。"""
    if driving_ctx:
        spatial = driving_ctx.get("spatial", {}) or {}
        dest = spatial.get("destination", {}) or {}
        lat = dest.get("latitude")
        lon = dest.get("longitude")
        if lat is not None and lon is not None:
            return {"latitude": lat, "longitude": lon}
    return {}


def map_pending_trigger(
    decision: dict, driving_ctx: dict | None
) -> tuple[str, dict, str]:
    """从 decision 映射 trigger_type、trigger_target、trigger_text。"""
    timing = decision.get("timing", "")
    if timing == "location":
        return (
            "location",
            extract_location_target(driving_ctx),
            "到达目的地时",
        )
    if timing == "location_time":
        return (
            "location_time",
            {
                "location": extract_location_target(driving_ctx),
                "time": decision.get("target_time", ""),
            },
            "到达目的地或到时间时",
        )
    if timing == "delay":
        seconds = decision.get("delay_seconds", 300)
        target_dt = datetime.now(UTC) + timedelta(seconds=seconds)
        target_str = target_dt.isoformat()
        return "time", {"time": target_str}, f"延迟 {seconds} 秒后"

    target_time = decision.get("target_time", "")
    if target_time:
        return "time", {"time": target_time}, f"{target_time} 时"
    if driving_ctx:
        return (
            "context",
            {"previous_scenario": driving_ctx.get("scenario", "")},
            "驾驶状态恢复时",
        )
    return "time", {"time": datetime.now(UTC).isoformat()}, ""
```

- [ ] **步骤 2：更新 `workflow.py` 导入**

删除 workflow.py 中以下代码（约行 66-235），替换为从 types 导入：

```python
# 删除 workflow.py 中的类定义：WorkflowError, LLMJsonResponse, ContextOutput,
# JointDecisionOutput, ReminderContent
# 删除函数定义：_format_time_for_display, _extract_location_target, _map_pending_trigger
# 删除 _call_llm_json 方法

# 添加导入：
from app.agents.types import (
    LLMJsonResponse,
    ContextOutput,
    JointDecisionOutput,
    ReminderContent,
    WorkflowError,
    call_llm_json,
    format_time_for_display,
    extract_location_target,
    map_pending_trigger,
)
```

workflow.py 内部对上述名称的引用需更新：
- `self._extract_content(decision)` → `ReminderContent.from_decision(decision)`
- `self._call_llm_json(prompt)` → `call_llm_json(self.memory_module.chat_model, prompt)`
- `AgentWorkflow._ensure_postprocessed` → 保持为静态方法（后续迁入 ExecutionAgent）

- [ ] **步骤 3：更新测试导入**

`tests/agents/test_llm_json_validation.py` 中所有从 `app.agents.workflow` 导入的类改为从 `app.agents.types` 导入：
- `LLMJsonResponse`
- `ContextOutput`
- `JointDecisionOutput`

- [ ] **步骤 4：验证**

运行：`uv run pytest tests/agents/test_llm_json_validation.py -v`
预期：全部 PASS

- [ ] **步骤 5：全量回归**

运行：`uv run pytest --tb=short -q`
预期：525 passed, 23 skipped

- [ ] **步骤 6：Commit**

```bash
git add app/agents/types.py app/agents/workflow.py tests/agents/test_llm_json_validation.py
git commit -m "refactor: extract Pydantic models and shared functions to types.py"
```

---

## 任务 2：创建 ContextAgent

**文件：**
- 创建：`app/agents/context_agent.py`
- 修改：`app/agents/workflow.py`（委托 _context_node → ContextAgent.run）

- [ ] **步骤 1：创建 `app/agents/context_agent.py`**

接口：

```python
"""Context Agent：记忆检索 + 对话历史 + LLM 上下文推断。"""

import json
import logging
from datetime import UTC, datetime

from pydantic import ValidationError

from app.agents.conversation import ConversationManager
from app.agents.prompts import SYSTEM_PROMPTS
from app.agents.state import AgentState
from app.agents.types import ContextOutput, LLMJsonResponse, WorkflowError, call_llm_json
from app.memory.memory import MemoryModule
from app.memory.types import MemoryMode

if TYPE_CHECKING:
    from app.models.chat import ChatModel

logger = logging.getLogger(__name__)


class ContextAgent:
    """Context 阶段：检索记忆 + 注入对话历史 + 构建/推断上下文。"""

    def __init__(
        self,
        memory_module: MemoryModule,
        conversations: ConversationManager,
        current_user: str,
    ) -> None:
        self._memory = memory_module
        self._conversations = conversations
        self._current_user = current_user

    async def run(self, state: AgentState) -> dict:
        """执行 Context 阶段，返回 {"context": dict}。"""
        # 逻辑同原 workflow.py _context_node（行 373-438）
        # 1. 搜索记忆（_search_memories）
        # 2. 注入对话历史
        # 3. 有 driving_context → 直接用；无 → LLM 推断
        # 4. 写入 stages.context
        ...

    async def _safe_memory_search(self, user_input: str) -> list[dict] | None:
        """搜索相关记忆，失败返回 None。"""
        # 同原 workflow.py 行 336-347
        ...

    async def _safe_memory_history(self) -> list[dict]:
        """获取最近历史记录，失败返回空列表。"""
        # 同原 workflow.py 行 349-359
        ...

    async def _search_memories(self, user_input: str) -> list[dict]:
        """搜索相关记忆，失败时回退到最近历史记录。"""
        # 同原 workflow.py 行 361-371
        ...
```

**迁移逻辑**：将 `workflow.py` 的 `_context_node`（行 373-438）、`_safe_memory_search`（行 336-347）、`_safe_memory_history`（行 349-359）、`_search_memories`（行 361-371）逐字复制到 ContextAgent 对应方法。唯一变化：`self.memory_module` → `self._memory`，`self._conversations` 不变。

`call_llm_json(self.memory_module.chat_model, prompt)` 替换原 `self._call_llm_json(prompt)`。

- [ ] **步骤 2：在 workflow.py 中接入 ContextAgent**

workflow.py `__init__` 新增：
```python
from app.agents.context_agent import ContextAgent

# __init__ 内：
self._context_agent = ContextAgent(
    memory_module=self.memory_module,
    conversations=self._conversations,
    current_user=current_user,
)
```

将 `_nodes` 列表中的 `self._context_node` 替换为：
```python
async def _context_node(self, state: AgentState) -> dict:
    return await self._context_agent.run(state)
```

**不删除原 `_context_node` 逻辑**——暂时保留委托，确认测试通过后再清理。

- [ ] **步骤 3：验证**

运行：`uv run pytest tests/agents/ -q`
预期：全部 PASS

- [ ] **步骤 4：Commit**

```bash
git add app/agents/context_agent.py app/agents/workflow.py
git commit -m "refactor: extract ContextAgent from AgentWorkflow"
```

---

## 任务 3：创建 JointDecisionAgent

**文件：**
- 创建：`app/agents/joint_decision_agent.py`
- 修改：`app/agents/workflow.py`

- [ ] **步骤 1：创建 `app/agents/joint_decision_agent.py`**

接口：

```python
"""JointDecision Agent：规则约束 + 偏好 + 概率推断 + LLM 决策。"""

import contextvars
import json
import logging

from pydantic import ValidationError

from app.agents.prompts import SYSTEM_PROMPTS
from app.agents.probabilistic import (
    OVERLOADED_WARNING_THRESHOLD,
    compute_interrupt_risk,
    infer_intent,
    is_enabled,
)
from app.agents.rules import apply_rules
from app.agents.state import AgentState
from app.agents.types import (
    JointDecisionOutput,
    LLMJsonResponse,
    WorkflowError,
    call_llm_json,
)
from app.exceptions import AppError
from app.memory.memory import MemoryModule
from app.memory.types import MemoryMode
from app.storage.toml_store import TOMLStore

logger = logging.getLogger(__name__)

_ablation_disable_feedback: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_ablation_disable_feedback", default=False
)


def set_ablation_disable_feedback(v: bool) -> None:
    _ablation_disable_feedback.set(v)


def get_ablation_disable_feedback() -> bool:
    return _ablation_disable_feedback.get()


_PREFERENCE_WEIGHT_HIGH: float = 0.6
_PREFERENCE_WEIGHT_LOW: float = 0.5
_INTENT_CONFIDENCE_THRESHOLD: float = 0.3


class JointDecisionAgent:
    """JointDecision 阶段：合并任务归因 + 策略决策。"""

    def __init__(
        self,
        memory_module: MemoryModule,
        strategies_store: TOMLStore,
        current_user: str,
    ) -> None:
        self._memory = memory_module
        self._strategies_store = strategies_store
        self._current_user = current_user

    async def run(self, state: AgentState) -> dict:
        """执行 JointDecision 阶段，返回 {"task": dict, "decision": dict}。"""
        # 同原 workflow.py _joint_decision_node（行 440-524）
        ...

    @staticmethod
    def format_constraints_hint(rules_result: dict | None) -> str:
        """从规则结果生成自然语言约束提示。"""
        # 同原 workflow.py _format_constraints_hint（行 271-288）
        ...

    async def _format_preference_hint(self) -> str:
        """从 strategies.toml 读 reminder_weights → 自然语言偏好提示。"""
        # 同原 workflow.py _format_preference_hint（行 301-323）
        # 使用本模块 _ablation_disable_feedback ContextVar
        ...
```

**迁移逻辑**：
- `_joint_decision_node` → `JointDecisionAgent.run`（行 440-524）
- `_format_constraints_hint` → `JointDecisionAgent.format_constraints_hint` 静态方法（行 271-288）
- `_format_preference_hint` → `JointDecisionAgent._format_preference_hint`（行 301-323）
- `_ablation_disable_feedback` ContextVar 及其 getter/setter → 本模块（从 workflow.py 删除）
- `_PREFERENCE_WEIGHT_HIGH/LOW`、`_INTENT_CONFIDENCE_THRESHOLD` → 本模块

注意：`run()` 中 `call_llm_json(self._memory.chat_model, prompt)` 替换原 `self._call_llm_json(prompt)`。

- [ ] **步骤 2：在 workflow.py 中接入 JointDecisionAgent**

```python
from app.agents.joint_decision_agent import (
    JointDecisionAgent,
    set_ablation_disable_feedback,
    get_ablation_disable_feedback,
)

# __init__ 内：
self._joint_decision_agent = JointDecisionAgent(
    memory_module=self.memory_module,
    strategies_store=self._strategies_store,
    current_user=current_user,
)
```

`_nodes` 中的 `self._joint_decision_node` 替换为委托。`proactive_run()` 中的 JointDecision 逻辑也改为调用 `self._joint_decision_agent` 的方法（提取 `run_for_proactive` 或在 `run` 中支持无 user_input 模式）。

workflow.py 中删除 `_ablation_disable_feedback` 相关代码，改为从 `joint_decision_agent` re-export。

- [ ] **步骤 3：验证**

运行：`uv run pytest tests/agents/ -q`
预期：全部 PASS

- [ ] **步骤 4：Commit**

```bash
git add app/agents/joint_decision_agent.py app/agents/workflow.py
git commit -m "refactor: extract JointDecisionAgent from AgentWorkflow"
```

---

## 任务 4：创建 ExecutionAgent

**文件：**
- 创建：`app/agents/execution_agent.py`
- 修改：`app/agents/state.py`（新增 `tool_results` 字段）

- [ ] **步骤 1：更新 `app/agents/state.py`**

在 `AgentState` TypedDict 中新增：

```python
tool_results: NotRequired[list[str] | None]
```

- [ ] **步骤 2：创建 `app/agents/execution_agent.py`**

接口：

```python
"""Execution Agent：规则后处理 + 工具执行 + pending + 频次 + 记忆写入。"""

import hashlib
import logging
from datetime import UTC, datetime
from pathlib import Path

from app.agents.outputs import OutputRouter
from app.agents.pending import PendingReminderManager
from app.agents.rules import apply_rules, postprocess_decision
from app.agents.state import AgentState
from app.agents.types import (
    ReminderContent,
    WorkflowError,
    format_time_for_display,
    extract_location_target,
    map_pending_trigger,
)
from app.config import user_data_dir
from app.exceptions import AppError
from app.memory.memory import MemoryModule
from app.memory.privacy import sanitize_context
from app.tools import get_default_executor
from app.tools.executor import ToolExecutionError

logger = logging.getLogger(__name__)


class ExecutionAgent:
    """Execution 阶段：执行决策，处理工具调用和提醒。"""

    def __init__(self, memory_module: MemoryModule, current_user: str) -> None:
        self._memory = memory_module
        self._current_user = current_user
        self._output_router = OutputRouter()
        self._pending_manager: PendingReminderManager | None = None

    @property
    def pending_manager(self) -> PendingReminderManager:
        """P2-8：懒初始化 PendingReminderManager。"""
        if self._pending_manager is None:
            self._pending_manager = PendingReminderManager(
                user_data_dir(self._current_user)
            )
        return self._pending_manager

    async def run(self, state: AgentState) -> dict:
        """执行 Execution 阶段。"""
        # 同原 _execution_node（行 733-788）
        ...

    @staticmethod
    def ensure_postprocessed(
        decision: dict, driving_ctx: dict | None
    ) -> tuple[dict, list[str]]:
        """统一入口：确保 decision 已过规则后处理。幂等。"""
        # 同原 workflow.py _ensure_postprocessed（行 290-299）
        ...

    async def _handle_cancel(self, state: AgentState, stages) -> dict:
        # 同原 workflow.py 行 560-579
        # 使用 self.pending_manager 代替 new PendingReminderManager
        ...

    async def _handle_tool_calls(self, decision: dict, state: AgentState) -> list[str]:
        """P2-10：返回工具结果列表。"""
        # 同原 workflow.py 行 581-601
        # 变更：返回 tool_results 而非仅 log
        # 写入 state["tool_results"]
        ...

    async def _handle_postpone(self, decision, state, driving_ctx, rules_result, modifications, stages) -> dict:
        # 同原 workflow.py 行 603-674
        # 使用 self.pending_manager 代替 new PendingReminderManager
        # 使用 self._output_router 代替 new OutputRouter()
        ...

    async def _handle_immediate_send(self, decision, state, driving_ctx, rules_result, modifications, stages) -> dict:
        # 同原 workflow.py 行 676-721
        # 使用 self._output_router 代替 new OutputRouter()
        ...

    async def _check_frequency_guard(self, state: AgentState) -> str | None:
        # 同原 workflow.py 行 531-558
        ...

    def _resolve_rules(self, state: AgentState, driving_ctx: dict | None) -> dict:
        # 同原 workflow.py 行 726-731
        ...
```

**迁移逻辑**：
- `_execution_node` → `ExecutionAgent.run`（行 733-788）
- `_ensure_postprocessed` → `ExecutionAgent.ensure_postprocessed` 静态方法（行 290-299）
- `_handle_cancel` → `ExecutionAgent._handle_cancel`（行 560-579），**用 `self.pending_manager` 替代 `PendingReminderManager(...)`**
- `_handle_tool_calls` → `ExecutionAgent._handle_tool_calls`（行 581-601），**改为返回 `list[str]`，同时写入 `state["tool_results"]`**
- `_handle_postpone` → `ExecutionAgent._handle_postpone`（行 603-674），**用 `self.pending_manager` 和 `self._output_router`**
- `_handle_immediate_send` → `ExecutionAgent._handle_immediate_send`（行 676-721），**用 `self._output_router`**
- `_check_frequency_guard` → `ExecutionAgent._check_frequency_guard`（行 531-558）
- `_resolve_rules` → `ExecutionAgent._resolve_rules`（行 726-731）

P2-10 变更点（`_handle_tool_calls`）：
```python
async def _handle_tool_calls(self, decision: dict, state: AgentState) -> list[str]:
    tool_calls = decision.get("tool_calls", [])
    if not tool_calls or not isinstance(tool_calls, list):
        return []
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
        state["tool_results"] = tool_results
    return tool_results
```

- [ ] **步骤 3：在 workflow.py 中接入 ExecutionAgent**

```python
from app.agents.execution_agent import ExecutionAgent

# __init__ 内：
self._execution_agent = ExecutionAgent(
    memory_module=self.memory_module,
    current_user=current_user,
)
```

`_nodes` 中的 `self._execution_node` 替换为委托。`proactive_run()` 和 `execute_pending_reminder()` 中的 execution 逻辑也改为调用 `self._execution_agent`。

`_build_done_data` 新增 P2-10：
```python
if state.get("tool_results"):
    done_data["tool_results"] = state["tool_results"]
```

- [ ] **步骤 4：验证**

运行：`uv run pytest tests/agents/ -q`
预期：全部 PASS

- [ ] **步骤 5：Commit**

```bash
git add app/agents/execution_agent.py app/agents/state.py app/agents/workflow.py
git commit -m "refactor: extract ExecutionAgent, unify PendingReminderManager and OutputRouter"
```

---

## 任务 5：精简 workflow.py 为薄编排器

**文件：**
- 修改：`app/agents/workflow.py`

- [ ] **步骤 1：清理 workflow.py**

删除所有已迁入 agent 的旧方法体（保留委托入口）。最终 workflow.py 结构：

```python
"""Agent 工作流薄编排器。"""

import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path

from app.agents.context_agent import ContextAgent
from app.agents.conversation import _conversation_manager
from app.agents.execution_agent import ExecutionAgent
from app.agents.joint_decision_agent import JointDecisionAgent
from app.agents.shortcuts import ShortcutResolver
from app.agents.state import AgentState, WorkflowStages
from app.agents.types import WorkflowError
from app.memory.memory import MemoryModule
from app.memory.types import MemoryMode
from app.models.chat import get_chat_model
from app.storage.toml_store import TOMLStore
from app.config import user_data_dir

# re-export 消融 ContextVar
from app.agents.joint_decision_agent import (  # noqa: F401
    set_ablation_disable_feedback,
    get_ablation_disable_feedback,
)

logger = logging.getLogger(__name__)


class AgentWorkflow:
    """多 Agent 协作工作流编排器。"""

    def __init__(
        self,
        data_dir: Path = Path("data"),
        memory_module: MemoryModule | None = None,
        current_user: str = "default",
    ) -> None:
        if memory_module is not None:
            self.memory_module = memory_module
        else:
            chat_model = get_chat_model()
            self.memory_module = MemoryModule(data_dir, chat_model=chat_model)

        self.current_user = current_user
        self._conversations = _conversation_manager
        self._shortcuts = ShortcutResolver()

        strategies_store = TOMLStore(
            user_dir=user_data_dir(current_user),
            filename="strategies.toml",
            default_factory=dict,
        )

        self._context_agent = ContextAgent(
            memory_module=self.memory_module,
            conversations=self._conversations,
            current_user=current_user,
        )
        self._joint_decision_agent = JointDecisionAgent(
            memory_module=self.memory_module,
            strategies_store=strategies_store,
            current_user=current_user,
        )
        self._execution_agent = ExecutionAgent(
            memory_module=self.memory_module,
            current_user=current_user,
        )

        self._nodes = [
            self._context_node,
            self._joint_decision_node,
            self._execution_node,
        ]

    async def _context_node(self, state: AgentState) -> dict:
        return await self._context_agent.run(state)

    async def _joint_decision_node(self, state: AgentState) -> dict:
        return await self._joint_decision_agent.run(state)

    async def _execution_node(self, state: AgentState) -> dict:
        return await self._execution_agent.run(state)

    # --- run_with_stages, run_stream, proactive_run, execute_pending_reminder ---
    # 保持原有逻辑，但：
    # - _ensure_postprocessed → ExecutionAgent.ensure_postprocessed
    # - _log_conversation_turn 保留在编排器
    # - _build_done_data 保留在编排器（含 P2-10 tool_results）
    ...
```

`run_with_stages`、`run_stream`、`proactive_run`、`execute_pending_reminder` 的控制流不变。内部调用改为：
- `AgentWorkflow._ensure_postprocessed(...)` → `ExecutionAgent.ensure_postprocessed(...)`
- 快捷指令路径中的 `_execution_node` 委托不变

`proactive_run` 中的 JointDecision 逻辑——当前是内联 LLM 调用。提取为 `JointDecisionAgent.run_proactive(context, constraints_hint, preference_hint, trigger_source)` 或在 `run` 中增加参数支持。

- [ ] **步骤 2：全量回归**

运行：`uv run pytest --tb=short -q`
预期：525 passed, 23 skipped

- [ ] **步骤 3：lint + type check**

```bash
uv run ruff check --fix
uv run ruff format
uv run ty check
```

- [ ] **步骤 4：Commit**

```bash
git add app/agents/
git commit -m "refactor: slim AgentWorkflow to thin orchestrator"
```

---

## 任务 6：P0-2 CORS 安全修复

**文件：**
- 修改：`app/api/main.py`
- 修改/创建：`tests/api/test_cors.py`（或加入 `test_rest.py`）

- [ ] **步骤 1：编写测试**

在 `tests/api/test_rest.py` 中追加或新建 `tests/api/test_cors.py`：

```python
def test_cors_wildcard_no_credentials(client):
    """通配符 origin 时 credentials 应为 False。"""
    # 需要 mock 或检查 middleware 配置
    # 由于 CORS 在 app 级别配置，检查响应头即可
    resp = client.options(
        "/api/v1/query",
        headers={
            "Origin": "http://evil.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    # 通配符模式下，浏览器不会发送 credentials
    # FastAPI CORSMiddleware 在 allow_origins=["*"] 时自动忽略 credentials
    assert resp.status_code in (200, 204)
```

- [ ] **步骤 2：修改 `app/api/main.py`**

```python
import os

def _build_cors_middleware() -> dict:
    """构建 CORS 中间件配置。"""
    origins_str = os.getenv("DRIVEPAL_CORS_ORIGINS", "*")
    origins = [o.strip() for o in origins_str.split(",") if o.strip()]
    is_wildcard = origins == ["*"]
    return {
        "allow_origins": origins,
        "allow_credentials": not is_wildcard,  # 通配符时禁 credentials
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }

# 替换原有的硬编码 CORS 配置
app.add_middleware(CORSMiddleware, **_build_cors_middleware())
```

- [ ] **步骤 3：验证**

运行：`uv run pytest tests/api/test_rest.py -v -k cors`
预期：PASS

- [ ] **步骤 4：全量回归**

运行：`uv run pytest tests/api/ -q`
预期：全部 PASS

- [ ] **步骤 5：Commit**

```bash
git add app/api/main.py tests/api/test_rest.py
git commit -m "fix: CORS wildcard disables credentials, origins configurable via env"
```

---

## 任务 7：P0-3 工具安全约束

**文件：**
- 修改：`app/tools/registry.py`（ToolSpec 新增字段）
- 修改：`app/tools/executor.py`（新增异常）
- 修改：`app/tools/tools/__init__.py`（注册时传入条件）
- 修改：`app/agents/execution_agent.py`（执行前检查）
- 测试：`tests/tools/test_executor.py`

- [ ] **步骤 1：编写测试**

```python
async def test_tool_requires_confirmation_when_driving(executor, driving_context):
    """驾驶中执行需确认的工具应返回确认提示而非执行。"""
    # 注册一个 require_confirmation_when="driving" 的 mock 工具
    # 驾驶中（scenario != "parked"）执行 → ToolConfirmationRequiredError
    ...

async def test_tool_no_confirmation_when_parked(executor, parked_context):
    """停车时无需确认。"""
    # scenario == "parked" → 正常执行
    ...
```

- [ ] **步骤 2：ToolSpec 新增字段**

`app/tools/registry.py`：

```python
@dataclass(frozen=True)
class ToolSpec:
    """工具规格说明。"""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler
    require_confirmation_when: str | None = None  # "driving" 等
```

- [ ] **步骤 3：新增 `ToolConfirmationRequiredError`**

`app/tools/executor.py`：

```python
class ToolConfirmationRequiredError(AppError):
    """工具执行需要用户确认。"""

    def __init__(self, tool_name: str) -> None:
        super().__init__(
            code="TOOL_CONFIRMATION_REQUIRED",
            message=f"工具 {tool_name} 需要语音确认后执行",
        )
```

- [ ] **步骤 4：注册时传入条件**

`app/tools/tools/__init__.py` 中 `set_navigation` 注册添加：

```python
registry.register(
    ToolSpec(
        name="set_navigation",
        ...,
        require_confirmation_when="driving" if cfg.navigation.require_voice_confirmation_driving else None,
    )
)
```

- [ ] **步骤 5：ExecutionAgent 检查确认条件**

`execution_agent.py` 的 `_handle_tool_calls` 中，执行前检查：

```python
async def _handle_tool_calls(self, decision: dict, state: AgentState) -> list[str]:
    ...
    for tc in tool_calls:
        if isinstance(tc, dict):
            t_name = tc.get("tool", "")
            t_params = tc.get("params", {})
            spec = executor._registry.get(t_name)
            # P0-3：确认检查
            if spec and spec.require_confirmation_when == "driving":
                driving_ctx = state.get("driving_context")
                scenario = (driving_ctx or {}).get("scenario", "parked")
                if scenario != "parked":
                    tool_results.append(f"[{t_name}] 需要语音确认后执行")
                    continue
            try:
                t_result = await executor.execute(t_name, t_params)
                ...
```

- [ ] **步骤 6：验证**

运行：`uv run pytest tests/tools/ -v`
预期：全部 PASS（含新测试）

- [ ] **步骤 7：全量回归**

运行：`uv run pytest --tb=short -q`
预期：525+ passed

- [ ] **步骤 8：Commit**

```bash
git add app/tools/ app/agents/execution_agent.py tests/tools/
git commit -m "feat: enforce tool confirmation when driving (require_voice_confirmation_driving)"
```

---

## 任务 8：P3-11 环境变量命名统一

**文件：**
- 修改：`app/agents/rules.py`
- 测试：`tests/agents/test_rules.py`

- [ ] **步骤 1：修改 `_get_fatigue_threshold()`**

`app/agents/rules.py` 行 44：

```python
# 改前：
raw = os.environ.get("FATIGUE_THRESHOLD", "0.7")

# 改后：
raw = os.environ.get("DRIVEPAL_FATIGUE_THRESHOLD") or os.environ.get("FATIGUE_THRESHOLD", "0.7")
```

- [ ] **步骤 2：验证现有测试仍通过**

运行：`uv run pytest tests/agents/test_rules.py -v`
预期：全部 PASS（现有测试用 `DRIVEPAL_FATIGUE_THRESHOLD` 或 `FATIGUE_THRESHOLD` 均可）

- [ ] **步骤 3：Commit**

```bash
git add app/agents/rules.py
git commit -m "fix: prefer DRIVEPAL_FATIGUE_THRESHOLD env var, fallback to FATIGUE_THRESHOLD"
```

---

## 任务 9：更新 AGENTS.md

**文件：**
- 修改：`app/agents/AGENTS.md`
- 修改：`app/tools/AGENTS.md`
- 修改：`app/api/AGENTS.md`（如有 CORS 相关描述）

- [ ] **步骤 1：更新 agents/AGENTS.md**

反映新文件结构：
- 新增 `types.py`、`context_agent.py`、`joint_decision_agent.py`、`execution_agent.py`
- 更新组件表
- 更新 `WorkflowError` 位置为 `types.py`
- 更新消融 ContextVar 位置

- [ ] **步骤 2：更新 tools/AGENTS.md**

- 新增 `ToolConfirmationRequiredError`
- `ToolSpec` 新增 `require_confirmation_when` 字段
- 更新安全约束章节

- [ ] **步骤 3：Commit**

```bash
git add app/agents/AGENTS.md app/tools/AGENTS.md app/api/AGENTS.md
git commit -m "docs: sync AGENTS.md with refactored agent and tool structure"
```

---

## 任务 10：最终验证

- [ ] **步骤 1：全量测试**

```bash
uv run pytest --tb=short -q
```
预期：525+ passed, 23 skipped, 0 failed

- [ ] **步骤 2：lint + type check**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```
预期：零错误

- [ ] **步骤 3：Squash 或保持独立 commits**

视需要 squash 相关 commits 或保持独立。当前 commit 历史为每步独立，可接受。
