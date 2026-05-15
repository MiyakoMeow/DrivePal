# 工具调用框架

`app/tools/` — 结构化工具定义、注册、执行。JointDecision LLM 输出 `tool_calls` 字段时触发。

## 架构

```mermaid
flowchart LR
    LLM["JointDecision LLM"] -->|tool_calls| EXEC["_execution_node"]
    EXEC --> TE["ToolExecutor"]
    TE --> REG["ToolRegistry"]
    REG --> NAV["set_navigation"]
    REG --> MEM["query_memory"]
    REG --> SND["send_message"]
    REG --> CLI["set_climate"]
    REG --> MED["play_media"]
```

## 组件

| 文件 | 类/函数 | 职责 |
|------|---------|------|
| `registry.py` | `ToolRegistry` | 注册/发现/描述工具 |
| `registry.py` | `ToolSpec` | 工具规范 dataclass（name/description/input_schema/handler） |
| `registry.py` | `ToolHandler` | `Callable[[dict[str, Any]], Awaitable[str]]` 类型 |
| `executor.py` | `ToolExecutor` | 参数校验 → handler 执行 → 结果文本 |
| `executor.py` | `ToolExecutionError` | 执行异常 |
| `__init__.py` | `get_default_executor()` | 默认单例 executor（注册全部内置工具） |
| `tools/navigation.py` | `navigate_to` | 导航目的地设置 |
| `tools/communication.py` | `send_message` | 消息发送 |
| `tools/vehicle.py` | `set_climate` / `play_media` | 车控预留（返回"未接入"）|
| `tools/memory_query.py` | `query_memory` | 记忆查询（使用单例 MemoryModule）|

## ToolSpec

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str                      # 唯一工具名
    description: str               # LLM 用描述
    input_schema: dict[str, Any]   # JSON Schema
    handler: ToolHandler           # async (dict) → str
```

## ToolRegistry

- `register(spec)` — 注册，重复名抛 `ValueError`
- `get(name)` — 按名查找，返回 `ToolSpec | None`（调用方需处理 None）
- `list_tools()` — 列出全部
- `to_llm_description()` — 格式化工具清单供 LLM prompt

## 内置工具

| 工具 | 参数 | 返回 |
|------|------|------|
| `set_navigation` | `destination: str` | `"导航已设置：{dest}"` |
| `send_message` | `recipient: str`, `message: str(max 200)` | `"消息已发送给 {recipient}"` |
| `query_memory` | `query: str` | top-5 记忆内容 |
| `set_climate` | `temperature: number(16-32)` | `"车控功能尚未接入"` |
| `play_media` | `name: str`, `type: music\|podcast` | `"媒体功能尚未接入"` |

### query_memory

- 使用 `get_memory_module()` 单例获取 MemoryModule
- 默认 top_k=5，读 `config/tools.toml` 的 `[tools.memory_query] max_results`
- 失败返回 `"记忆查询失败"`（不抛异常）

## 工具执行（`_handle_tool_calls`）

工具调用执行已提取为独立方法 `_handle_tool_calls()`（`app/agents/workflow.py:581`）。`_execution_node` 内流程顺序：

1. 规则后处理 `postprocess_decision()` — 强制覆盖
2. **工具调用执行** — `_handle_tool_calls()`
3. 待触发提醒创建 — `postpone`/`timing` 分支生成 PendingReminder
4. `_check_frequency_guard()` — 频次抑制

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

结果仅 log，不写回 state——工具调用的副作用（导航设置/消息发送等）已在 handler 内完成。

## 配置

值来源 `config/tools.toml`（不存在于源码——首次调用 `ToolsConfig.load()` 时由 `ensure_config()` 自动生成，内容为 dataclass 默认值）。

```toml
[tools.navigation]
enabled = true
require_voice_confirmation_driving = true

[tools.communication]
enabled = true
max_message_length = 200

[tools.vehicle]
enabled = false
temperature_min = 16
temperature_max = 32

[tools.memory_query]
enabled = true
max_results = 5
```

注册时按 `enabled` 标志过滤（`is_enabled()`），`enabled=false` 的工具不会被注册；已注册工具执行时不再检查。

## 异常

| 异常 | 文件 | 继承 | 说明 |
|------|------|------|------|
| `ToolExecutionError` | `executor.py:16` | `AppError` | 参数校验/handler异常，code=TOOL_ERROR |

catch 模式：`_handle_tool_calls()` 逐工具 `except ToolExecutionError` → 错误文本追加至 `tool_results`，**不抛**；`WorkflowError`/`AppError` 透传。配置由 `ToolsConfig.load()` → `ensure_config()` 处理——文件缺失/损坏时自动用 dataclass 默认值生成 `config/tools.toml`。注册表不会因配置缺失变空。

## 安全约束

工具调用受规则引擎 `postprocess_decision()` 统一管辖（`proactive_run` 路径必走规则后处理）。当前规则引擎不区分工具类型——所有 `tool_calls` 在 LLM 输出中存在即被执行，工具级别约束待后续细化。

## 测试

`tests/tools/test_registry.py` — 注册 + 重复注册检测。
