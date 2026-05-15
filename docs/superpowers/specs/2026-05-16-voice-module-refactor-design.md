# 语音模块重构：独立开关 + 独立测试 + WebUI 监控

## 目标

1. 语音模块可通过配置或 API 独立开启/关闭
2. 语音模块可独立测试（CLI + 独立服务进程）
3. WebUI 语音控制台（嵌入现有页面，侧边栏第二页）

## 设计

### VoiceService — 核心抽象

`app/voice/service.py` — 封装生命周期。

```
VoiceService
├── start(sched: ProactiveScheduler | None = None) → bool
├── stop()
├── update_config(cfg: dict) → VoiceConfig
├── get_transcriptions(limit: int = 50) → list[dict]
├── status → VoiceStatus
│   ├── enabled: bool
│   ├── running: bool
│   ├── vad_status: str
│   ├── device_index: int
│   └── config: dict
└── _transcription_history: deque[dict]  环形缓冲 200 条
```

内部状态：
- `pipeline: VoicePipeline | None`
- `recorder: VoiceRecorder | None`
- `consume_task: asyncio.Task | None`
- `running: bool = False`

### 配置

`config/voice.toml` 新增 `enabled` 字段：

```toml
[voice]
enabled = true
device_index = 0
sample_rate = 16000
vad_mode = 1
min_confidence = 0.5
silence_timeout_ms = 500
```

`VoiceConfig` 新增 `enabled: bool = True`。`_toml_defaults()` 同步。

### API 路由

新增 `app/api/v1/voice.py`，挂载到 `API_V1`：

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/voice/status` | `VoiceService.status` dict |
| POST | `/api/v1/voice/start` | 开始录音（受 enabled 约束） |
| POST | `/api/v1/voice/stop` | 停止录音 |
| GET | `/api/v1/voice/config` | 当前配置 |
| PUT | `/api/v1/voice/config` | 热更新配置（部分参数需重启生效，返回实际生效配置） |
| GET | `/api/v1/voice/transcriptions` | 历史转录（`?limit=N`，默认 50，最大 200） |
| GET | `/api/v1/voice/devices` | 可用麦克风列表（`{index, name, channels}`） |

`voice_service` 通过 `app.state.voice_service` 注入。

现有 `app/api/main.py` 改动：
- `_init_voice_if_available()` + `_stop_voice()` 删除
- lifespan 内创建 `VoiceService`，挂到 `app.state`
- `API_V1.include_router(voice_router, prefix="/voice", tags=["voice"])`

### WebUI

`index.html` 侧边栏第二页。左栏两模式切换：

```
┌──────────────────┐
│ [驾驶模拟] [语音] │  ← tab
├──────────────────┤
│ （模式切换时内容替换） │
│                    │
│ 语音模式左栏：      │
│ ┌────────────────┐ │
│ │ 录音开关        │ │
│ │ [● 录音中]      │ │
│ │ 设备选择        │ │
│ │ [Microphone ▾]  │ │
│ │ VAD 状态指示    │ │
│ │ 🟢 说话中 / ⚪   │ │
│ │ 配置（折叠）    │ │
│ │ VAD mode: [1 ▾]│ │
│ │ 置信度: [0.5]   │ │
│ │ [应用]          │ │
│ └────────────────┘ │
├──────────────────┤
│ 右栏：             │
│ ┌────────────────┐ │
│ │ 实时转录区域    │ │
│ │ 今天天气不错    │ │
│ │ 我要去王府井    │ │
│ │ ...            │ │
│ └────────────────┘ │
│ ┌────────────────┐ │
│ │ 转录历史        │ │
│ │ 12:30 今天天气..│ │
│ │ 12:32 我要去王..│ │
│ └────────────────┘ │
└──────────────────┘
```

`app.js` 加：
- `switchMode(mode)` — 切换「驾驶模拟」/「语音」tab
- `startVoicePolling()` / `stopVoicePolling()` — 语音 mode 激活时轮询
- 轮询 `/api/v1/voice/status` 每 500ms（VAD + 运行状态）
- 轮询 `/api/v1/voice/transcriptions?since=<last_id>` 每 1s
- `updateVoiceConfig()` — PUT `/api/v1/voice/config`
- `toggleRecording()` — POST `/api/v1/voice/start|stop`

`styles.css` 新增语音面板样式。

### CLI

`app/voice/__main__.py`（`python -m app.voice`） + `app/voice/cli.py`：

```
$ python -m app.voice --help
usage: voice-cli [-h] [--list-devices] [--device INDEX]

$ python -m app.voice --list-devices
  0: USB Microphone (2 channels)
  1: Built-in Audio (2 channels)

$ python -m app.voice --device 0
  [INFO] Starting voice pipeline...
  [VAD:speech     ] 今天天气不错
  [VAD:silence    ]
  [VAD:speech     ] 我要去王府井
  ^C
  [INFO] Stopped.
```

实现：直接创建 `VoiceService`，`start()` 时传自定义 `on_transcription` 回调（打印到终端）。用 `anyio` 或 `asyncio` 运行。

### 独立服务

`app/voice/server.py`（`python -m app.voice.server`）：

```python
# 轻量 FastAPI，仅语音路由 + 静态文件
app = FastAPI(lifespan=_lifespan)
app.state.voice_service = VoiceService()
# 挂 /api/v1/voice/* 路由 + / + /static
if __name__ == "__main__":
    uvicorn.run(app, host=host, port=port)
```

不初始化 scheduler/memory/workflow。`start()` 传 `sched=None`，转录不进 memory 但存环形缓冲供 API 查。

入口脚本 `scripts/voice-server.sh`：

```bash
#!/usr/bin/env bash
uv run python -m app.voice.server "$@"
```

### 文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `app/voice/service.py` | **新增** | VoiceService 类 |
| `app/voice/cli.py` | **新增** | CLI 入口逻辑 |
| `app/voice/__main__.py` | **新增** | `python -m app.voice` |
| `app/voice/server.py` | **新增** | 独立语音服务 |
| `app/voice/config.py` | 修改 | VoiceConfig 加 `enabled` 字段 |
| `config/voice.toml` | 修改 | 加 `enabled = true` |
| `app/api/v1/voice.py` | **新增** | 语音 REST 路由 |
| `app/api/main.py` | 修改 | lifespan 用 VoiceService |
| `webui/index.html` | 修改 | 加语音 tab + 面板 |
| `webui/app.js` | 修改 | 语音控制逻辑 |
| `webui/styles.css` | 修改 | 语音面板样式 |

## 错误处理

- `VoiceService.start()`: enabled=False → 静默返回 False，不抛异常
- `VoiceService.start()`: 已运行 → 幂等，返回 True，日志 info
- `VoiceService.stop()`: 未运行 → 幂等，不抛异常
- `VoiceService.update_config()`: 配置无效 → 抛 ValueError，不修改当前配置
- API: 语音未启用时 POST `/start` → 返回 400 `{"error": {"code": "VOICE_DISABLED", "message": "Voice is disabled in config"}}`
- API: 已运行时 POST `/start` → 返回 409 `{"error": {"code": "ALREADY_RUNNING"}}`
- CLI: 设备不存在 → 打印错误并 exit(1)
- CLI: ASR 模型缺失 → warn 并继续（空转录输出）

## 测试策略

- `tests/voice/test_service.py`：VoiceService 生命周期（mock Pipeline/Recorder）
- `tests/voice/test_cli.py`：CLI 参数解析 + list-devices
- `tests/api/test_voice_api.py`：API 端点（start/stop/status/config）
- 集成：独立服务进程启动 + API 调用

## 未解决问题

1. 热更新配置时 VAD mode / sample_rate 需重建 Pipeline — 当前设计：参数变更时 stop + start 自动生效
2. 独立服务不初始化 scheduler，转录不进 MemoryBank — 临时存储于环形缓冲，适合调试/答辩场景
3. WebUI 实时转录用轮询而非 WebSocket — 简化实现，500ms 间隔对 UI 展示足够
