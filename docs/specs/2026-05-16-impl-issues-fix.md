# 实现问题修复设计

日期：2026-05-16
范围：排除 voice 模块（ASR ImportError 降级）和消融实验模块

## 变更总览

| ID | 优先级 | 问题 | 方案 |
|----|--------|------|------|
| P0-2 | 高 | CORS `allow_origins=["*"]` + `allow_credentials=True` | env var 控制，通配符时禁 credentials |
| P0-3 | 高 | 工具安全约束 `require_voice_confirmation_driving` 未执行 | ExecutionAgent 检查工具确认条件 |
| P1-4 | 高 | AgentWorkflow 1109 行 God class | 拆为 ContextAgent / JointDecisionAgent / ExecutionAgent + 薄编排器 |
| P2-8 | 中 | PendingReminderManager 生命周期不一致 | 统一为 ExecutionAgent 懒初始化成员 |
| P2-9 | 低 | OutputRouter 重复实例化 | ExecutionAgent 构造时实例化一次 |
| P2-10 | 低 | Tool call 结果仅 log 不回传 | 写入 state，纳入 done 事件 |
| P3-11 | 低 | `FATIGUE_THRESHOLD` 命名不一致 | 优先 `DRIVEPAL_FATIGUE_THRESHOLD`，回退旧名 |

## P0-2：CORS 安全

**文件**：`app/api/main.py`

**当前**：
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    ...)
```

**改为**：
- 读 `DRIVEPAL_CORS_ORIGINS` 环境变量（逗号分隔），默认 `"*"`
- `origins = ["*"]` 时：`allow_credentials=False`（浏览器规范要求）
- 显式指定来源时：`allow_credentials=True`

## P0-3：工具安全约束

**文件**：`app/tools/executor.py`、`app/agents/execution_agent.py`（新）

**方案**：

1. `ToolSpec` 新增 `require_confirmation_when: str | None` 字段（值：`"driving"` 等）
2. `ToolExecutor.execute()` 执行前检查：若 `require_confirmation_when == "driving"` 且驾驶中（scenario 非 `"parked"`），抛 `ToolConfirmationRequiredError(AppError)`
3. `ExecutionAgent._handle_tool_calls()` catch 此异常 → 将确认提示写入 `state["tool_results"]`
4. `_build_done_data()` 将 tool_results 纳入 done 事件

**注册时传入**：`register_builtin_tools()` 从 `ToolsConfig` 读取各工具的 confirmation 字段，写入 ToolSpec。

## P1-4：AgentWorkflow 深度重构

### 新文件结构

```
app/agents/
  types.py              ← 新：Pydantic 模型 + 辅助函数 + WorkflowError
  context_agent.py      ← 新：ContextAgent
  joint_decision_agent.py ← 新：JointDecisionAgent
  execution_agent.py    ← 新：ExecutionAgent
  workflow.py           ← 改：薄编排器
```

### types.py（~170 行）

从 `workflow.py` 迁出：

| 类/函数 | 说明 |
|---------|------|
| `LLMJsonResponse` | LLM JSON 输出包装 |
| `ContextOutput` | Context Agent 输出模型（含 AliasChoices） |
| `JointDecisionOutput` | JointDecision 输出模型（含 AliasChoices） |
| `ReminderContent` | 提醒内容提取 |
| `WorkflowError` | 工作流异常 |
| `call_llm_json()` | 共享 LLM JSON 调用（从 `_call_llm_json` 提取为模块级函数） |
| `format_time_for_display()` | ISO 时间 → HH:MM |
| `extract_location_target()` | driving_ctx → 目标位置 |
| `map_pending_trigger()` | decision → trigger_type/target/text |

### ContextAgent（~100 行）

**依赖**：`MemoryModule`、`ConversationManager`、`ChatModel`（通过 MemoryModule）

**接口**：
```python
class ContextAgent:
    def __init__(self, memory_module: MemoryModule, conversations: ConversationManager, current_user: str): ...
    async def run(self, state: AgentState) -> dict: ...
```

**封装**：
- `_context_node` 全部逻辑
- `_search_memories` / `_safe_memory_search` / `_safe_memory_history`
- 对话历史注入

### JointDecisionAgent（~130 行）

**依赖**：`ChatModel`、`MemoryModule`（概率推断）、`TOMLStore`（偏好）、`ConversationManager`（读消融 ContextVar）

**接口**：
```python
class JointDecisionAgent:
    def __init__(self, memory_module: MemoryModule, strategies_store: TOMLStore, current_user: str): ...
    async def run(self, state: AgentState) -> dict: ...
```

**封装**：
- `_joint_decision_node` 全部逻辑
- `_format_preference_hint`
- `_format_constraints_hint`（静态方法）
- 概率推断集成
- 消融 ContextVar `_ablation_disable_feedback`

### ExecutionAgent（~350 行）

**依赖**：`MemoryModule`、`OutputRouter`、`PendingReminderManager`、`ToolExecutor`、`user_data_dir`

**接口**：
```python
class ExecutionAgent:
    def __init__(self, memory_module: MemoryModule, current_user: str): ...
    async def run(self, state: AgentState) -> dict: ...
    @staticmethod
    def ensure_postprocessed(decision: dict, driving_ctx: dict | None) -> tuple[dict, list[str]]: ...
```

**封装**：
- `_execution_node` 全部逻辑
- `_handle_cancel` / `_handle_postpone` / `_handle_immediate_send` / `_handle_tool_calls`
- `_check_frequency_guard` / `_resolve_rules`
- `_extract_content`
- **P2-8**：`_pending_manager` 懒初始化成员（统一 cancel/postpone/poll）
- **P2-9**：`_output_router = OutputRouter()` 构造时实例化
- **P2-10**：`_handle_tool_calls` 将结果写入 `state["tool_results"]`
- **P0-3**：工具确认条件检查

### AgentWorkflow 薄编排器（~300 行）

**保留**：
- `__init__`：创建三个 Agent + ShortcutResolver
- `run_with_stages()` / `run_stream()` / `proactive_run()` / `execute_pending_reminder()`
- `_build_done_data()`（含 P2-10 tool_results）
- `_log_conversation_turn()`
- 消融 ContextVar 导出函数（`set_ablation_disable_feedback` / `get_ablation_disable_feedback`）

**委托**：
- `_context_node` → `self._context_agent.run(state)`
- `_joint_decision_node` → `self._joint_decision_agent.run(state)`
- `_execution_node` → `self._execution_agent.run(state)`

### 公共接口不变

所有外部调用签名保持不变：
- `AgentWorkflow.run_with_stages(user_input, driving_context, session_id)`
- `AgentWorkflow.run_stream(user_input, driving_context, session_id)`
- `AgentWorkflow.proactive_run(context_override, memory_hints, trigger_source)`
- `AgentWorkflow.execute_pending_reminder(content, driving_context, trigger_source)`

## P2-8：PendingReminderManager 生命周期

ExecutionAgent 构造函数初始化 `self._pending_manager: PendingReminderManager | None = None`。

首次需要时通过属性懒初始化：
```python
@property
def pending_manager(self) -> PendingReminderManager:
    if self._pending_manager is None:
        self._pending_manager = PendingReminderManager(user_data_dir(self._current_user))
    return self._pending_manager
```

所有路径（cancel / postpone / poll 通过 scheduler）使用同一实例。

## P2-10：Tool call 结果回传

`_handle_tool_calls()` 将结果追加到 `state["tool_results"]`（list[str]）。

`_build_done_data()` 在 done 事件中包含：
```python
if state.get("tool_results"):
    done_data["tool_results"] = state["tool_results"]
```

## P3-11：环境变量命名

`rules.py` 中 `_get_fatigue_threshold()` 改为：
```python
raw = os.environ.get("DRIVEPAL_FATIGUE_THRESHOLD") or os.environ.get("FATIGUE_THRESHOLD", "0.7")
```

## 不在范围内

| 排除项 | 原因 |
|--------|------|
| P0-1 ASR ImportError | voice 模块由其他工作树处理 |
| P1-5 AgentState 无验证 | deep refactoring 自然改善 |
| P1-6 单例不一致 | 用户选择不统一 |
| P2-7 decision dict 无 schema | 用户选择不加 |
| P2-12 conversation 纯内存 | 设计决策，非 bug |
| P2-13 bg_tasks 未接入 | 不在修复范围 |

## 影响文件清单

| 文件 | 动作 |
|------|------|
| `app/agents/types.py` | 新建 |
| `app/agents/context_agent.py` | 新建 |
| `app/agents/joint_decision_agent.py` | 新建 |
| `app/agents/execution_agent.py` | 新建 |
| `app/agents/workflow.py` | 重写为薄编排器 |
| `app/agents/__init__.py` | 更新导出 |
| `app/agents/state.py` | 可能新增 `tool_results` 字段 |
| `app/api/main.py` | CORS 修改 |
| `app/tools/executor.py` | 工具确认检查 |
| `app/tools/registry.py` | ToolSpec 新增字段 |
| `app/tools/__init__.py` | 注册时传入 confirmation |
| `app/agents/rules.py` | 环境变量命名 |
| `app/scheduler/scheduler.py` | 适配 ExecutionAgent 接口变化（如有） |
| `tests/agents/test_*.py` | 适配新结构 |
| `tests/api/test_rest.py` | CORS 测试补充 |
| `tests/tools/test_executor.py` | 确认检查测试 |
| 各模块 `AGENTS.md` | 同步文档 |
