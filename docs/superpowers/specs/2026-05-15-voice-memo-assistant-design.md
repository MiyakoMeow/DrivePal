# 车载智能备忘录设计文档

> 基于 DrivePal 现有 Agent 管道 + MemoryBank，扩展为被动录音 + 主动提醒 + 工具调用的车载智能助手。

## 背景

现有 DrivePal 为 query-response 架构：用户输入文本 → AgentWorkflow 处理 → 响应。
目标改为三层能力：

| 层 | 说明 |
|----|------|
| 被动记录 | 车载麦克风持续监听，自动 ASR 转录并写入记忆 |
| 主动提醒 | 后台调度器轮询上下文+记忆，在恰当时机主动推送 |
| 工具调用 | Execution 节点扩展结构化工具执行 |

## 架构总览

```
Mic ─→ VoicePipeline ─→ ASR 文本 ─→┐
传感器 ─→ ContextProvider ───────────┤──→ ProactiveScheduler
                                     │      │
                                  ┌──┘      │ (触发)
                                  ▼         ▼
                              MemoryBank  AgentWorkflow
                               (读写)     (被动/主动模式)
                                            │
                                       ┌────┴────┐
                                       │         │
                                   ToolExec.  OutputRouter
                                              (TTS/HUD)
```

## 模块设计

### 1. 语音流水线 (`app/voice/`)

sherpa-onnx 本地 ASR，离线可用，中文支持完善。

组件：

| 文件 | 职责 |
|------|------|
| `pipeline.py` | VoicePipeline 编排：recorder → vad → asr → 文本输出 |
| `recorder.py` | VoiceRecorder：pyaudio 管理麦克风，ring buffer 持续录音 |
| `vad.py` | VADEngine：webrtcvad/silero-vad，切分语音段，丢弃非语音 |
| `asr.py` | ASREngine：sherpa-onnx 封装，`transcribe(audio_bytes) → (text, confidence)` |

流程：
1. 车辆上电 → `VoicePipeline.start()`
2. 录音线程持续写入 ring buffer
3. VAD 检测到语音起始 → 开始录音段
4. VAD 检测到语音结束 → 录音段送入 ASR
5. ASR 输出文本 + 置信度
6. 低置信度（<min_confidence）丢弃；高置信度写 MemoryBank（event_type 为 `passive_voice`）
7. 同时推入 Scheduler 的 asyncio.Queue——下个 tick 消费，兼顾低延迟与去抖

配置项 (`config/voice.toml`)：

| 项 | 说明 |
|----|------|
| device_index | 麦克风设备 ID |
| sample_rate | 采样率 (16000) |
| vad_mode | VAD 灵敏度 (0-3) |
| min_confidence | 最低置信度 (0.5) |
| silence_timeout_ms | 静音超时切分 (500) |

### 2. 主动调度器 (`app/scheduler/`)

后台 asyncio 循环，将系统从"被动响应"转为"主动触发"。

组件：

| 文件 | 职责 |
|------|------|
| `scheduler.py` | ProactiveScheduler：主循环，可启停，可配间隔 |
| `context_monitor.py` | 缓存上次 driving_context，检测增量变化 |
| `memory_scanner.py` | 调 MemoryBank.search() 检索当前相关记忆 |
| `trigger_evaluator.py` | 合并各路信号判断是否触发提醒 |

检查周期：`TICK_INTERVAL_SECONDS=15`（可配置）。

ASR 转录文本通过 asyncio.Queue 推入调度器——非即时打断，下个 tick 消费。此机制天然提供去抖窗口（同源 15s 内重复触发合并），且比独立事件通道更简单可靠。

**触发源评估：**

| 源 | 方法 | 条件 |
|----|------|------|
| 上下文变化 | 对比缓存/driving_context 差异 | scenario/location/speed 变化超阈值 |
| 位置接近 | 计算记忆事件位置 ↔ 当前位置 haversine | <500m（默认） |
| 定时 | 检查 PendingReminder + 当前时间 | ≥target_time |
| 状态驱动 | 检查 fatigue/workload 阈值 | fatigue>0.7 或 workload=overloaded |
| 周期性回顾 | 每日固定时间扫描一日记忆 | configurable time |

**触发决策矩阵：**

`trigger_evaluator.py` 综合各源信号 + 规则引擎约束，判断：

1. 是否有足够新的触发信号——去抖窗口 `DEBOUNCE_SECONDS=30`，同源触发在窗口内合并
2. 当前驾驶场景是否允许提醒（规则引擎）
3. 距离上次提醒是否满足频次限制
4. 是否需要紧急打断（interrupt_level 0/1/2）

通过后 → 调用 `AgentWorkflow.proactive_run()`。

### 3. 工具调用框架 (`app/tools/`)

结构化工具执行，集成到 Execution 节点。

组件：

| 文件 | 职责 |
|------|------|
| `registry.py` | ToolRegistry：注册/发现工具，每工具有 name+desc+input_schema |
| `executor.py` | ToolExecutor：参数校验(Pydantic) → 执行 → 结果封装 |
| `tools/navigation.py` | 导航工具（设目的地） |
| `tools/communication.py` | 消息工具（发短信/IM） |
| `tools/vehicle.py` | 车控工具（空调/媒体） |
| `tools/memory_query.py` | 记忆查询工具 |

**工具定义：**

```python
@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict  # JSON Schema
    handler: Callable[[dict], Awaitable[str]]
```

**JointDecision 输出扩展：**

```json
{
  "should_remind": true,
  "tool_calls": [
    {"tool": "set_navigation", "params": {"destination": "北京西站"}}
  ]
}
```

**安全约束：**

| 工具 | 行驶中 | 停车 | 紧急模式 |
|------|--------|------|----------|
| set_navigation | 仅语音确认 | 允许 | 允许 |
| send_message | 仅语音合成 | 允许 | 允许 |
| call_contact | 禁止 | 允许 | 允许 |
| query_memory | 允许 | 允许 | 允许 |

安全约束由规则引擎 `postprocess_decision()` 统一实施，工具调用也受其管辖。

### 4. AgentWorkflow 扩展

**新增 `proactive_run()` 方法：**

```python
async def proactive_run(
    context_override: DrivingContext | None = None,
    memory_hints: list[SearchResult] | None = None,
    trigger_source: str = "scheduler",
) -> WorkflowResult:
```

与现有 `run_with_stages()` 区别：
- 无 user_query 字段
- Context 阶段跳过 LLM 推断（直接用外部上下文）
- JointDecision prompt 改为"根据驾驶上下文+记忆，判断是否需要主动提醒"
- 仍走规则引擎 + 频次限制 + 隐私脱敏

**提示词调整：**
- 现有：用户 query + 上下文 + 记忆 → 决策
- 主动模式：上下文 + 记忆 + 触发源说明 → 决策是否需要提醒

### 5. 现有组件修改

| 文件 | 变更 |
|------|------|
| `app/agents/workflow.py` | 加 `proactive_run()`，修改 `run_stream()` 支持被动模式 SSE |
| `app/agents/prompts.py` | 加主动模式 system prompt |
| `app/agents/pending.py` | trigger_type 扩展 `state`/`periodic` |
| `app/agents/execution.py` | 集成 ToolExecutor |
| `app/memory/schemas.py` | MemoryEvent.type 扩展 `passive_voice`（与 ASR 转录一致） |
| `app/api/main.py` | lifespan 启停 scheduler + voice |
| `app/api/v1/ws_manager.py` | 服务端主动 push reminder 事件 |

### 6. 多用户

已有 per-user MemoryBank。扩展：

| 场景 | 用户标识 |
|------|---------|
| 语音 | 用户切换时配置 VoicePipeline.user_id |
| 调度器 | ProactiveScheduler per-user 实例 |
| 上下文 | 已有 X-User-Id header |

## 配置

### `config/voice.toml`

```toml
[voice]
device_index = 0
sample_rate = 16000
vad_mode = 1
min_confidence = 0.5      # 范围 [0,1]，<此值丢弃
silence_timeout_ms = 500
```

### `config/scheduler.toml`

```toml
[scheduler]
tick_interval_seconds = 15
debounce_seconds = 30         # 同源触发合并窗口
enable_periodic_review = true
review_time = "08:00"
location_proximity_meters = 500
```

### `config/tools.toml`

```toml
[tools.navigation]
enabled = true
require_voice_confirmation_driving = true

[tools.communication]
enabled = true
max_message_length = 200

[tools.vehicle]
enabled = false  # 预留

[tools.memory_query]
enabled = true
max_results = 5
```

## 未解决问题

1. 真实 ASR 集成依赖 sherpa-onnx 的 Python binding 可用性——先做接口抽象，具体引擎后续绑
2. ContextProvider 目前由 WebUI 模拟，真实车辆总线集成超出本文档范围
3. TTS 输出——本设计产出 speakable_text，实际 TTS 引擎为独立组件
4. 语音唤醒词——当前始终监听，后续可加唤醒词减少误触发

## 与现有系统的关系

| 现有代码 | 关系 |
|----------|------|
| AgentWorkflow (agents/) | 核心——扩展 proactive_run，不改原有 query-response 流程 |
| MemoryBank (memory/) | 核心——不变，新增写入 passive_event 类型 |
| 规则引擎 (agents/rules.py) | 核心——不变，工具调用也受约束 |
| PendingReminder (agents/pending.py) | 扩展——新增 trigger_type |
| 输出路由 (agents/outputs.py) | 不变 |
| 隐私脱敏 (memory/privacy.py) | 不变 |
| 反馈学习 (api/feedback) | 不变 |
| WebUI | 不变——仍用于开发测试 |
