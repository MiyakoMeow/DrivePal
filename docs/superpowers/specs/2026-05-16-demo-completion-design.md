# 演示补全与功能完善 — 设计文档

> 创建：2026-05-16 | 分支：`feat/demo-completion`

## 目标

补全知行车秘项目所有已知功能缺口，优先保障论文答辩演示体验。

**执行策略**：四子项目各独立计划，按 A→B→C→D 顺序逐次执行。本文档为统一设计规格，各子项目实现时拆分独立 implementation plan。

**优先级分级**：

| 等级 | 子项目 | 时限 |
|------|--------|------|
| **P0 答辩前必须** | A（演示体验） | 答辩前完成 |
| **P1 答辩前加分** | C（生产化） | 答辩前完成 |
| **P2 答辩后补充** | B（语音补全） | 答辩后完成 |
| **P3 未来工作** | D（车辆集成） | 无硬性时限 |

---

## 子项目 A：演示体验

### A1. 演示预设场景

启动时自动播种 5 个 seed presets，仅在预设为空时创建。

**实现**：`app/storage/init_data.py` 新增 `_seed_demo_presets()`，在 `init_storage()` 末尾调用。

**5 个预设**：

| 名称 | 场景 | 关键字段 | 演示用途 |
|------|------|----------|----------|
| 🅿️ 停车场准备出发 | parked | workload=normal, fatigue=0.1, 北京东城区 | 查询创建提醒 |
| 🛣️ 高速公路巡航 | highway | speed=120, workload=normal, passengers, 京藏高速 | 规则引擎演示 |
| 🚦 城市拥堵通勤 | traffic_jam | congestion_level=congested, fatigue=0.4, 北京三环 | 情境提醒演示 |
| 😴 疲劳驾驶警告 | highway | fatigue=0.8, workload=high, speed=100 | 安全规则演示 |
| 🎙️ 语音录入 | parked | workload=low, 北京 | 语音转录演示 |

**约束**：预设为普通数据，可删改。仅在 `presets.toml` 不存在或无有效 preset 时写入。不重复创建。

### A2. 演示脚本

**文件**：`docs/demo-script.md`

**格式**：Markdown，含操作步骤 + 串词。

**6 幕流程**（约 7 分钟）：

| 幕 | 时间 | 操作 | 串词要点 |
|----|------|------|----------|
| 1. 开场 | 30s | 展示首页 | 系统定位：车载AI智能体。三条数据流：被动记录、主动提醒、查询响应 |
| 2. 查询演示 | 90s | 选🅿️预设 → 输入"明天上午9点开会" → 展开四阶段 | 三阶段工作流可解释性，外部上下文直接注入跳过LLM编造 |
| 3. 语音演示 | 90s | 切🎙️标签 → 开始录音 → 说"提醒我下午3点去加油" → 看转录 | 被动记录，零配置记忆，自动写入MemoryBank |
| 4. 规则演示 | 60s | 选🛣️预设 → 输入"提醒我给老张打电话" → 看规则约束 | 7条硬规则不可绕过：高速仅音频通道，频次限制30分钟 |
| 5. 主动提醒 | 60s | 选🚦预设 → 等待调度器触发 → WS推送 | 5种触发源：时间/位置/场景/状态/周期。15秒轮询去抖 |
| 6. 反馈学习 | 30s | 点接受/忽略按钮 → 看权重变化 | 偏好学习反馈闭环，Ebbinghaus遗忘曲线 |

**输出**：脚本为参考，非硬性约束。答辩者可按实际节奏调整。

### A3. WebUI 修复

**3 项修复**：

1. **实验图表静默降级**：`loadExperimentData()` 失败时不显示 error 卡片，隐藏图表区域。当前：Canvas 上绘制错误文字 → 改为：整个 `.experiment-section` 设置 `display:none`
2. **TTS 播放控件**：Execution done 事件中，若 payload 含 `audio_base64`，创建 `<audio>` 元素自动播放（依赖 A4）。注意浏览器自动播放限制：需用户先交互过（如点发送按钮），首次播放前 `audio.play()` 需 catch 并提示"点击任意位置启用语音"
3. **语音设备加载失败静默**：`loadVoiceDevices()` 失败时不阻塞整体 UI，仅在设备选择框显示"无可用设备"

### A4. TTS 接入

**新增文件**：`app/voice/tts.py`

**TTSClient 类**：

```
TTSClient
  ├── synthesize(text: str) -> bytes   # 调用 edge-tts，返回 MP3
  ├── _cache: dict[str, bytes]         # LRU 缓存，60s TTL
  └── 降级：edge-tts 不可用时静默跳过
```

**实现细节**：
- 使用 `edge-tts` 库（`pip install edge-tts`）
- 音色：`zh-CN-XiaoxiaoNeural`（微软中文女声，自然度高）
- 合成：`edge-tts --voice zh-CN-XiaoxiaoNeural --text "..." --write-media /tmp/tts.mp3`
- 异步调用：`asyncio.create_subprocess_exec`
- 缓存：同文本 60s 内不重复合成，LRU 淘汰最多 50 条

**配置**：`config/voice.toml` 新增：

```toml
[voice.tts]
enabled = false          # 默认关闭
voice = "zh-CN-XiaoxiaoNeural"
```

**启用方式**：环境变量 `DRIVEPAL_TTS_ENABLED=1` 覆盖配置。API 层已有 `PUT /api/v1/voice/config` 可热切换。

**集成点**：
- `ExecutionAgent`：产出 `speakable_text` 后调用 `tts_client.synthesize(text)` → 将 base64 MP3 注入 `done` SSE 事件
- WebUI：`handleWSMessage('done')` 中检测 `data.audio_base64`，创建 `<audio>` 元素并播放
- 非 WebUI 场景：不播放，仅记录日志

**依赖**：`edge-tts` 加入 `pyproject.toml` 可选依赖组 `[project.optional-dependencies].tts`。主依赖不强制，静默降级。

### A5. README 修正

修正过时 API 路径：
- `/api/query` → `/api/v1/query`
- `/api/query/stream` → WebSocket 流式（`/api/v1/ws`）
- `/api/feedback` → `/api/v1/feedback`
- `/api/history` → `/api/v1/history`
- `/api/presets` → `/api/v1/presets`
- `/api/export` → `/api/v1/export`
- `/api/data` → `/api/v1/data`

同时修正 README 中模块架构树（`stream.py` 已不存在，`routes/` 已合并至 `v1/`）。

---

## 子项目 B：语音补全（P2，答辩后）

### B1. 唤醒词检测

**方案**：VAD 前插入 sherpa-onnx keyword spotter。

**实现**：`app/voice/pipeline.py` 新增 `KeywordSpotter` 包装类。

```
VoicePipeline 流程（新）：
  Mic → KeywordSpotter → VAD → ASR
         ↑ 唤醒前：音频直通不处理
         ↓ 唤醒后：N秒无语音 → 自动休眠
```

**配置**：`config/voice.toml` 新增：

```toml
[voice.wake_word]
enabled = false
keyword = "知行车秘"
model = "data/models/sherpa-onnx-kws/model.onnx"  # 需手动下载
timeout_seconds = 10  # 唤醒后无语音超时
```

**模型**：sherpa-onnx 关键词识别模型（约 5MB），需单独下载。未下载时静默降级。

**约束**：答辩前不实现。默认关闭。答辩时可提及为"未来工作"。

### B2. Speaker ID

**方案**：SenseVoice 不支持 speaker identification。使用 wespeaker 提取 speaker embedding + 简单聚类。

**实现**：
- 新增 `app/voice/speaker.py`：`SpeakerIdentifier` 类
- 集成到 `VoicePipeline`：转录完成后提取 speaker embedding
- 与已知 speaker 比对（余弦相似度），阈值 > 0.7 归为已有 speaker

**配置**：`config/voice.toml` 新增：

```toml
[voice.speaker_id]
enabled = false
model = "data/models/wespeaker/voxceleb_resnet34.onnx"  # 需手动下载
threshold = 0.7
```

**约束**：标注为"实验性功能"。模型需手动下载（约 30MB）。答辩场景不必须。

### B3. 多用户语音识别

**方案**：VoicePipeline 接受 `user_id` 参数，转录结果标记 `speaker`。

**实现**：
- `VoiceService.start()` 接受可选 `user_id` 参数
- WebUI 语音 tab 新增用户选择下拉（默认 `default`）
- 转录 API 返回增加 `speaker` 字段

**约束**：仅 UI 层改动 + 参数透传。无 Speaker ID 时 `speaker` 字段为空。

---

## 子项目 C：生产化

### C1. Per-user Scheduler 启用

**现状**：`app/api/main.py::_lifespan` 中 `_schedulers` dict 存在，但仅初始化 `default` 用户。

**方案**：
- 新增 `POST /api/v1/scheduler/start`（body: `{"user_id": "xxx"}`），动态创建并启动
- 新增 `POST /api/v1/scheduler/stop`（body: `{"user_id": "xxx"}`）
- WebSocket 连接时，若该 user_id 无 scheduler，自动懒创建

**实现**：
- `app/api/main.py`：将 `_schedulers` 提升为模块级变量 `_SCHEDULERS`
- `app/api/v1/scheduler.py`：新增路由文件
- `app/agents/workflow.py`：`AgentWorkflow` 构造函数已接受 `current_user`，无需改动

**约束**：scheduler 创建需传入 `AgentWorkflow` 实例 + `MemoryModule` + `ws_manager`，这些在 lifespan 中已初始化，需确保生命周期正确。

### C2. 集成测试补全

**scheduler 集成测试**（3 个场景）：
1. **位置触发**：`ContextMonitor` 检测到位置变化 ≥ 500m → `TriggerEvaluator` 判定触发 → `proactive_run` 被调用
2. **场景触发**：`ContextMonitor` 检测到 scenario 从 `city_driving` → `parked` → 触发"停车时回顾提醒"
3. **去抖**：30s 内连续变化 → 仅触发一次

**tools 集成测试**（2 个场景）：
1. **导航工具确认**：`scenario=highway` 时 LLM 返 `tool_calls=[navigation]` → `ToolExecutor` 抛 `ToolConfirmationRequiredError` → 规则引擎验证
2. **工具结果注入**：Mock 工具返成功 → 验证结果注入 JointDecision 输出

**voice + memory 联调测试**（1 个场景）：
1. VAD → ASR 产出文本"明天下午3点加油" → `MemoryBank.add()` → 30s 后 `MemoryBank.search("加油")` 能检索到

**实现位置**：`tests/scheduler/test_integration.py`、`tests/tools/test_integration.py`、`tests/voice/test_memory_integration.py`。

### C3. 突发事件模块（不需实现）

当前由 `JointDecisionAgent` + 规则引擎联合覆盖。在 AGENTS.md 注明即可，不新增独立模块。

---

## 子项目 D：车辆集成

### D1. ContextProvider 抽象

**方案**：定义 `ContextProvider` Protocol，统一上下文来源。

```python
from typing import Protocol

class ContextProvider(Protocol):
    """驾驶上下文提供者接口。"""
    async def get_context(self, user_id: str) -> DrivingContext | None: ...
```

**实现**：
- `WebUIContextProvider`：从 API 请求/WebSocket 消息中提取（现有实现的形式化）
- 预留 `CANBusContextProvider`、`OBDContextProvider`（标注为未来工作）

**集成**：`ProactiveScheduler.update_context()` 接受 `ContextProvider`。调度器轮询时调用 `provider.get_context()`。

### D2. OBD 模拟器

**方案**：创建 `OBDSimulator`，从 CSV/JSONL 回放真实行车数据。

**实现**：
- 新增 `app/scheduler/obd_simulator.py`：`OBDSimulator` 类
- 读取 `data/obd_trace.csv`（时间戳,车速,转速,油温,油量,...）
- `async play(user_id)` → 按时间戳顺序 yield `DrivingContext`
- 调度器可订阅模拟器数据流

**数据格式**（CSV）：
```csv
timestamp,speed_kmh,rpm,coolant_temp,fuel_level
0,0,800,25,80
5,30,2000,35,78
10,60,2500,40,75
```

**约束**：`data/obd_trace.csv` 需手动准备（示例数据可内置）。默认不启用。论文答辩场景不必须。

---

## 依赖关系

```
A（演示体验）── 无前置，可独立启动
  ├── A1 无依赖
  ├── A2 无依赖
  ├── A3#1（实验图表）无依赖
  ├── A3#2（TTS 播放控件）依赖 A4（TTSClient）—— 但 A3#2 可先实现 UI，A4 完成后串联
  ├── A3#3（设备静默）无依赖
  ├── A4 无依赖（edge-tts 独立库）
  └── A5 无依赖
B（语音补全）── 依赖 A4（共用 voice.toml 配置段）
C（生产化）  ── 无前置，可独立启动
D（车辆集成）── 依赖 C1（scheduler 需支持 per-user）
```

## 文件变更清单

| 子项目 | 新增文件 | 修改文件 |
|--------|----------|----------|
| A1 | — | `app/storage/init_data.py` |
| A2 | `docs/demo-script.md` | — |
| A3 | — | `webui/app.js`, `webui/styles.css`, `webui/index.html` |
| A4 | `app/voice/tts.py` | `app/agents/execution_agent.py`, `webui/app.js`, `config/voice.toml`, `pyproject.toml` |
| A5 | — | `README.md` |
| B1 | — | `app/voice/pipeline.py`, `config/voice.toml` |
| B2 | `app/voice/speaker.py` | `app/voice/pipeline.py`, `config/voice.toml` |
| B3 | — | `app/voice/service.py`, `webui/app.js`, `webui/index.html`, `app/api/v1/voice.py` |
| C1 | `app/api/v1/scheduler.py` | `app/api/main.py` |
| C2 | 若干 `tests/**/*.py` | — |
| D1 | `app/schemas/context_provider.py` | `app/scheduler/scheduler.py` |
| D2 | `app/scheduler/obd_simulator.py` | — |

## 不实现

- **真实 CAN 总线集成**：需 OBD-II 硬件 + python-OBD，不在本次范围。标注为长期未来工作。
- **ASR 模型优化**：SenseVoice int8 量化已可用，不进一步优化。
- **容器化/Docker**：论文答辩不需要，不在此次范围。

## 验收标准

### 子项目 A

| 项 | 通过标准 |
|----|----------|
| A1 | 清空 `presets.toml` 后重启服务，WebUI 预设下拉菜单显示 5 个 seed presets |
| A2 | `docs/demo-script.md` 存在，含 6 幕操作步骤 + 串词，按此脚本可完成全程演示 |
| A3 | 实验图表区域在无数据时不显示错误；TTS 按钮在 A4 启用后可见；语音设备加载失败不阻塞 UI |
| A4 | 设 `DRIVEPAL_TTS_ENABLED=1` 后，查询返回 `speakable_text` 时 WebUI 自动播放语音；edge-tts 不可用时静默降级 |
| A5 | `README.md` 中所有 API 路径与 `app/api/v1/` 实际路由一致 |

### 子项目 B

| 项 | 通过标准 |
|----|----------|
| B1 | 唤醒词模型存在时，说"知行车秘"后 VAD 开始检测；无模型时静默降级 |
| B2 | Speaker embedding 可用时，连续两段语音归为同一 speaker；无模型时静默降级 |
| B3 | WebUI 语音 tab 可选用户；转录 API 返回含 `speaker` 字段 |

### 子项目 C

| 项 | 通过标准 |
|----|----------|
| C1 | `POST /api/v1/scheduler/start {"user_id":"test"}` 创建并启动新 scheduler；WS 连接新用户时自动创建 |
| C2 | 新增 6 个集成测试全部通过 |

### 子项目 D

| 项 | 通过标准 |
|----|----------|
| D1 | `ContextProvider` Protocol 定义存在；`ProactiveScheduler` 可接受 `ContextProvider` 实例 |
| D2 | 给定 `data/obd_trace.csv`，`OBDSimulator.play()` 按时间顺序 yield `DrivingContext` |
