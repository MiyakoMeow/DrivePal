# 代码整合与范式统一设计

## 背景

全系统经分析发现 7 类结构性问题：错误处理碎片化、workflow 过度集中、配置与代码脱节、单例管理混乱、state 可变共享、代码重复、时区处理不一致。

## 设计目标

1. 统一异常体系为 `AppError` 继承树
2. 拆分 `_execution_node()`、缓存 `apply_rules()`、删除弃用代码
3. 接线配置字段、统一单例管理、修复时区问题
4. 补全高优模块测试（scheduler tick、tools executor、voice pipeline）

## 一、统一异常体系

### 1.1 新增 `app/exceptions.py`

```python
class AppError(Exception):
    """全系统异常基类。"""
    code: str
    message: str

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)
```

### 1.2 模块异常改继承

| 模块 | 原基类 | 改为 |
|------|--------|------|
| `memory/exceptions.py` `MemoryBankError` | `Exception` | `AppError` |
| `models/chat.py` `ChatError` | `Exception` | `AppError` |
| `tools/executor.py` `ToolExecutionError` | `RuntimeError` | `AppError` |
| `agents/workflow.py` `ChatModelUnavailableError` | `RuntimeError` | `AppError`（重命名 `WorkflowError`） |

各模块异常名不变（`MemoryBankError` 仍是 `MemoryBankError`），仅改基类为 `AppError`。`WorkflowError` 为新名，替代 `ChatModelUnavailableError`。

### 1.3 API 层 `safe_call()`

替代 `safe_memory_call()`，通用异常边界：

```python
def safe_call[T](coro: Coroutine[Any, Any, T], context_msg: str) -> T:
    """catch AppError → 按子类型映射 HTTP 状态码；非 AppError → 500"""
```

映射规则：
- `TransientError` → 503
- `FatalError` / `IndexIntegrityError` → 500
- `ValidationError` → 422（Pydantic）
- `WorkflowError` → 503
- `ToolError` → 500
- 其他 `AppError` → 500
- 非 `AppError` → 500 + log full traceback

### 1.4 去掉宽泛异常清单

`workflow.py` / `scheduler.py` 中的 `except (OSError, ValueError, RuntimeError, TypeError, KeyError)` 改为 `except AppError`。外部库异常（`openai.APIError` 等）在 models 层捕获并转为 `AppError` 子类。

### 1.5 异常链

所有跨层异常转换使用 `raise X from Y`。

## 二、`workflow.py` 拆分

### 2.1 `_execution_node()` 拆分

提取 6 个私有方法：

| 方法 | 职责 | 原行范围 |
|------|------|---------|
| `_handle_cancel()` | cancel_last action 直接返回 | ~610-620 |
| `_handle_postpone()` | postprocess + postpone/delay → PendingReminder | ~620-690 |
| `_check_frequency()` | 频次检查，返回抑制消息或 None | ~580-595 |
| `_handle_tool_calls()` | 工具调用执行 + 日志 | ~650-670 |
| `_handle_pending_creation()` | location/time → PendingReminder | ~670-700 |
| `_handle_immediate_send()` | 即时发送：内容提取 + OutputRouter + 隐私脱敏 + Memory 写入 | ~700-788 |

`_execution_node()` 缩减为路由方法，按决策字段分发。

### 2.2 `apply_rules()` 缓存

在 `_joint_decision_node()` 首次调用 `apply_rules()` 后，结果存入 `state["rules_result"]`。后续 `_execution_node()` 各子方法从 state 读取。

`_format_constraints_hint()` 改为接收 `rules_result` 参数而非重新调用 `apply_rules()`。

### 2.3 删除弃用代码

- `TaskOutput` (workflow.py:131-156) — 确认无外部导入后删除
- `StrategyOutput` (workflow.py:158-181) — 确认无引用后删除

### 2.4 `_haversine()` 统一

提取到 `app/utils.py`，`pending.py` 和 `context_monitor.py` 均从该处导入。

## 三、配置接线 + 单例 + 时区

### 3.1 `scheduler.toml` 接线

`ProactiveScheduler.__init__()` 读取 `enable_periodic_review` 和 `review_time`（解析 "HH:MM" 格式），替代硬编码 `_REVIEW_HOUR` / `_REVIEW_WINDOW_MINUTES`。

### 3.2 `tools.toml` 的 `enabled` 接线

`register_builtin_tools()` 读取 `config/tools.toml`，仅注册 `enabled=true` 的工具。

### 3.3 `voice.toml` 统一加载

`VoicePipeline.__init__()` 加载配置一次，将参数传给 `VADEngine` 和 `ASREngine` 构造函数，不再各自加载。

### 3.4 `_FRAME_BYTES` 清理

删除 `constants.py` 中的 `_FRAME_BYTES`。`VADEngine` 自行根据 `sample_rate` 和 `frame_ms` 计算。`pipeline.py` 的帧大小检查改为从 `VADEngine` 实例读取。

### 3.5 时区修复

- `parse_time()` 返回 `datetime` 对象（带 tzinfo）而非 ISO 字符串
- `_check_time()` 直接比较 `datetime` 对象
- `periodic` 触发使用 `datetime.now().astimezone()` 取本地时间

### 3.6 `_PER_USER_LOCKS` 清理

改为 `WeakValueDictionary`，无引用的 Lock 自动回收。

### 3.7 `compute_interrupt_risk()` key 统一

统一使用 `driver` 作为 driving_context 中驾驶员状态字段的 key。`ContextOutput` 的 `driver_state` 字段在注入 `state["driving_context"]` 时映射为 `driver`。

### 3.8 `communication.py` 配置缓存

`send_message()` 首次加载 `tools.toml` 的 `max_length` 后缓存，不再每次调用重读。

### 3.9 `experiment_store.py` 异步化

`read_benchmark()` 改用 `aiofiles`。

### 3.10 `JSONLinesStore.append()` mkdir 优化

目录创建移到 `__init__`，`append()` 跳过 `mkdir`。

## 四、测试补全

### 4.1 Scheduler 测试（~10 个）

- `_tick()` 完整流程：voice drain → pending poll → context update → signals → evaluate
- `_build_signals()` 各触发源独立测试
- `_drain_voice_queue()` 语音消费 + 写入失败降级
- `_poll_pending()` reminder 轮询 + proactive_run 调用
- `_evaluate_and_execute()` 评估 → 执行 → WS 广播
- `periodic` 时间窗口逻辑
- 规则约束（`only_urgent`/`postpone`）交互

### 4.2 Tools Executor 测试（~8 个）

- 未知工具 → `ToolError`
- 参数校验：缺 required、类型错误、min/max 违规
- handler 异常 → `ToolError`
- 各内置工具（navigation/communication/memory_query/vehicle）正常调用
- `enabled=false` 的工具不注册

### 4.3 Voice Pipeline 测试（~6 个）

- 正常 VAD → ASR 流水线
- 置信度过滤
- ASR 不可用 → 空文本降级
- 帧大小不匹配 → 跳过
- 回调触发
- `VoiceRecorder` 不测试（依赖 pyaudio 硬件）

## 不在范围内

- `AppContext` 单例聚合类（改动过大）
- `AgentState` TypedDict → dataclass/immutable（影响面太广）
- `stages.decision` 同步逻辑重构
- 工具结果反馈给 LLM 的 follow-up turn
- WS user_id 验证、CORS 生产配置（安全功能，非本次范畴）
