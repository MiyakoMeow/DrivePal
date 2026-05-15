# 语音模块重构实现计划

> **面向执行者：** 使用 subagent-driven-development 逐任务实现。步骤用 `- [ ]` 跟踪。

**目标：** VoiceService 封装 + 配置/API开关 + CLI + 独立服务 + WebUI 语音控制台

**技术栈：** Python 3.14, FastAPI, asyncio, pyaudio, webrtcvad, sherpa-onnx

**规格：** `docs/superpowers/specs/2026-05-16-voice-module-refactor-design.md`

---

## 文件结构

| 操作 | 文件 | 职责 |
|------|------|------|
| 修改 | `app/voice/config.py` | VoiceConfig 加 `enabled` 字段 |
| 新建 | `app/voice/service.py` | VoiceService 封装生命周期 |
| 新建 | `app/voice/cli.py` | CLI 命令行入口 |
| 新建 | `app/voice/__main__.py` | `python -m app.voice` |
| 新建 | `app/voice/server.py` | 独立语音 FastAPI 服务 |
| 修改 | `app/voice/__init__.py` | 导出 VoiceService |
| 新建 | `app/api/v1/voice.py` | 语音 REST 路由 |
| 修改 | `app/api/main.py` | lifespan 集成 VoiceService（任务 4） |
| 修改 | `webui/index.html` | 侧边栏第二页（语音 tab） |
| 修改 | `webui/app.js` | 语音控制逻辑 |
| 修改 | `webui/styles.css` | 语音面板样式 |
| 新建 | `tests/voice/test_service.py` | VoiceService 单元测试 |
| 新建 | `tests/api/test_voice_api.py` | 语音 API 测试 |

---

### 任务 1：VoiceConfig 加 enabled 字段

**文件：** `app/voice/config.py`

- [ ] **步骤 1：VoiceConfig 加 `enabled: bool = True` 字段**

```python
@dataclass
class VoiceConfig:
    device_index: int = 0
    enabled: bool = True  # 新增
    sample_rate: int = 16000
    # ... 其余不变
```

- [ ] **步骤 2：`_toml_defaults()` 同步输出 enabled**

```python
return {
    "voice": {
        "enabled": cfg.enabled,  # 新增
        "device_index": cfg.device_index,
        # ...
    },
}
```

- [ ] **步骤 3：`load()` 读取 enabled 字段**

```python
return cls(
    enabled=voice_data.get("enabled", cls.enabled),  # 新增
    device_index=voice_data.get("device_index", cls.device_index),
    # ...
)
```

- [ ] **步骤 4：修改 `config/voice.toml` 加 enabled 字段**

在 `config/voice.toml` 的 `[voice]` 节加：

```toml
[voice]
enabled = true
device_index = 0
```

- [ ] **步骤 5：Commit**

```bash
git add app/voice/config.py config/voice.toml
git commit -m "feat: add enabled field to VoiceConfig + voice.toml"
```

---

### 任务 2：VoiceService 核心类

**文件：** 新建 `app/voice/service.py` + 新建 `tests/voice/test_service.py`

`VoiceService` 接口：

```python
class VoiceService:
    def __init__(self, config: VoiceConfig | None = None):
        cfg = config or VoiceConfig.load()
        self._enabled = cfg.enabled
        self._pipeline: VoicePipeline | None = None
        self._recorder: VoiceRecorder | None = None
        self._consume_task: asyncio.Task | None = None
        self._running = False
        self._on_transcription: Callable[[str, float], None] | None = None
        self._transcription_history: deque[dict] = deque(maxlen=200)
        self._vad_status: str = "idle"

    @property
    def status(self) -> dict:
        """当前运行状态，含 enabled/running/vad_status/device_index/config。"""
        return {
            "enabled": self._enabled,
            "running": self._running,
            "vad_status": self._vad_status,
            "device_index": VoiceConfig.load().device_index,
            "config": {
                "device_index": VoiceConfig.load().device_index,
                "sample_rate": VoiceConfig.load().sample_rate,
                "vad_mode": VoiceConfig.load().vad_mode,
                "min_confidence": VoiceConfig.load().min_confidence,
            },
        }

    async def start(
        self,
        sched: ProactiveScheduler | None = None,
        *,
        on_transcription: Callable[[str, float], None] | None = None,
    ) -> bool:
        # enabled=False → return False
        # 已运行 → return True（幂等）
        # 创建 Pipeline + Recorder + consume task
        # on_transcription 回调优先级：传入 > 内部（写 history + 转发 sched）
        # 传入回调与内部回调链式调用

    async def stop(self) -> None:
        # 幂等，取消 task + close pipeline + stop recorder

    async def update_config(self, cfg: dict) -> dict:
        # 热更新配置。无效配置（如 vad_mode 非 0-3）抛 ValueError
        # 返回 {applied, requires_restart, running}

    async def get_transcriptions(self, limit: int = 50) -> list[dict]:
        # 取最近 limit 条

    async def get_devices(self) -> list[dict]:
        # pyaudio.PyAudio().list_devices()

    async def toggle_recording(self, start: bool) -> bool:
        # 运行时动态启停录音
```

- [ ] **步骤 1：写 VoiceService 测试（先 mock Pipeline/Recorder）**

`tests/voice/test_service.py`：

```python
"""测试 VoiceService 生命周期."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.voice.service import VoiceService


@pytest.mark.asyncio
async def test_start_enabled_true_starts_pipeline():
    """Given enabled=True, When start(), Then pipeline/recorder 被创建."""
    svc = VoiceService.__new__(VoiceService)
    svc._enabled = True
    svc._running = False
    svc._pipeline = None
    svc._recorder = None
    svc._consume_task = None
    svc._on_transcription = None
    svc._transcription_history = []
    svc._vad_status = "idle"

    with (
        patch("app.voice.service.VoicePipeline") as MockPipeline,
        patch("app.voice.service.VoiceRecorder") as MockRecorder,
    ):
        mock_p = MockPipeline.return_value
        mock_r = MockRecorder.return_value

        async def _empty_run():
            """空 async generator，for _consume 用。"""
            return
            yield

        mock_p.run = _empty_run

        result = await svc.start()

        assert result is True
        assert svc._pipeline is not None
        assert svc._recorder is not None
        MockPipeline.assert_called_once()
        MockRecorder.assert_called_once()
        mock_r.start.assert_called_once_with(mock_p)


@pytest.mark.asyncio
async def test_start_enabled_false_noop():
    """Given enabled=False, When start(), Then 不创建任何东西，返回 False."""
    svc = VoiceService(config=MagicMock(enabled=False))
    result = await svc.start()
    assert result is False
    assert svc._pipeline is None


@pytest.mark.asyncio
async def test_stop_idempotent():
    """Given 未启动, When stop(), Then 不抛异常."""
    svc = VoiceService(config=MagicMock(enabled=True))
    await svc.stop()  # 不应抛


@pytest.mark.asyncio
async def test_status_reflects_state():
    """Given 启动后, When status, Then 反映实际状态."""
    svc = VoiceService.__new__(VoiceService)
    svc._enabled = True
    svc._running = True
    svc._pipeline = MagicMock()
    svc._recorder = MagicMock()
    svc._vad_status = "speech"
    svc._on_transcription = None
    svc._transcription_history = []
    svc._consume_task = MagicMock()

    st = svc.status
    assert st["enabled"] is True
    assert st["running"] is True
    assert st["vad_status"] == "speech"
    assert "device_index" in st
    assert "config" in st
    assert isinstance(st["config"], dict)


@pytest.mark.asyncio
async def test_get_transcriptions_returns_history():
    """Given 有历史, When get_transcriptions(2), Then 返回最近 2 条."""
    svc = VoiceService.__new__(VoiceService)
    svc._transcription_history = [
        {"text": "a", "confidence": 0.9, "timestamp": "1"},
        {"text": "b", "confidence": 0.8, "timestamp": "2"},
        {"text": "c", "confidence": 0.95, "timestamp": "3"},
    ]
    svc._enabled = True
    svc._running = False
    svc._pipeline = None
    svc._recorder = None
    svc._consume_task = None
    svc._on_transcription = None
    svc._vad_status = "idle"

    result = await svc.get_transcriptions(limit=2)
    assert len(result) == 2
    assert result[0]["text"] == "c"


@pytest.mark.asyncio
async def test_get_devices_returns_list():
    """Given pyaudio 可用, When get_devices(), Then 返设备列表."""
    svc = VoiceService(config=MagicMock(enabled=True))
    with patch("pyaudio.PyAudio") as MockPyAudio:
        mock_pa = MockPyAudio.return_value
        mock_pa.get_device_count.return_value = 2
        mock_pa.get_device_info_by_index.side_effect = [
            {"index": 0, "name": "Mic", "maxInputChannels": 1},
            {"index": 1, "name": "Speaker", "maxInputChannels": 0},
        ]
        devices = await svc.get_devices()
        assert len(devices) == 1  # 仅输入设备
        assert devices[0]["name"] == "Mic"
```

- [ ] **步骤 2：运行测试，预期失败（ImportError — service.py 不存在）**

```bash
cd .worktrees/voice-refactor && uv run pytest tests/voice/test_service.py -v --timeout=10
```

- [ ] **步骤 3：实现 VoiceService**

`app/voice/service.py`：

```python
"""VoiceService — 语音服务生命周期封装。"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Callable

from app.voice.config import VoiceConfig
from app.voice.pipeline import VoicePipeline
from app.voice.recorder import VoiceRecorder

if TYPE_CHECKING:
    from app.scheduler import ProactiveScheduler

logger = logging.getLogger(__name__)

_HISTORY_MAXLEN = 200


class VoiceService:
    """封装 VoicePipeline + VoiceRecorder 生命周期。提供统一启停/状态/配置接口。"""

    def __init__(self, config: VoiceConfig | None = None) -> None:
        cfg = config or VoiceConfig.load()
        self._enabled = cfg.enabled
        self._pipeline: VoicePipeline | None = None
        self._recorder: VoiceRecorder | None = None
        self._consume_task: asyncio.Task | None = None
        self._running = False
        self._on_transcription: Callable[[str, float], None] | None = None
        self._transcription_history: deque[dict] = deque(maxlen=_HISTORY_MAXLEN)
        self._vad_status: str = "idle"

    @property
    def status(self) -> dict:
        """当前运行状态。"""
        cfg = VoiceConfig.load()
        return {
            "enabled": self._enabled,
            "running": self._running,
            "vad_status": self._vad_status,
            "device_index": cfg.device_index,
            "config": {
                "device_index": cfg.device_index,
                "sample_rate": cfg.sample_rate,
                "vad_mode": cfg.vad_mode,
                "min_confidence": cfg.min_confidence,
            },
        }

    async def start(
        self,
        sched: ProactiveScheduler | None = None,
        *,
        on_transcription: Callable[[str, float], None] | None = None,
    ) -> bool:
        """启动语音流水线。enabled=False 时静默返回 False。幂等。"""
        if not self._enabled:
            logger.info("Voice disabled by config, skipping start")
            return False
        if self._running:
            logger.debug("Voice already running")
            return True

        def _on_transcription(text: str, confidence: float) -> None:
            """内部回调：写历史 + 可选转发 scheduler + 可选外部回调。"""
            self._transcription_history.append({
                "text": text,
                "confidence": confidence,
                "timestamp": datetime.now(UTC).isoformat(),
            })
            if sched is not None:
                try:
                    asyncio.create_task(sched.push_voice_text(text))
                except Exception:
                    logger.exception("Failed to push voice text to scheduler")
            if on_transcription is not None:
                try:
                    on_transcription(text, confidence)
                except Exception:
                    logger.exception("External on_transcription callback failed")

        self._on_transcription = _on_transcription

        try:
            pipeline = VoicePipeline(on_transcription=self._on_transcription)
            recorder = VoiceRecorder()

            await recorder.start(pipeline)

            async def _consume() -> None:
                async for text in pipeline.run():
                    pass  # 回调已处理

            task = asyncio.create_task(_consume())

            self._pipeline = pipeline
            self._recorder = recorder
            self._consume_task = task
            self._running = True
            logger.info("Voice service started")
            return True
        except Exception as e:
            logger.warning("Voice service start failed: %s", e)
            await self._cleanup()
            return False

    async def stop(self) -> None:
        """停止流水线。幂等。"""
        if not self._running and self._consume_task is None:
            return
        self._running = False
        await self._cleanup()
        logger.info("Voice service stopped")

    async def _cleanup(self) -> None:
        """清理内部资源。"""
        if self._consume_task is not None:
            self._consume_task.cancel()
            try:
                await self._consume_task
            except asyncio.CancelledError:
                pass
            self._consume_task = None
        if self._pipeline is not None:
            await self._pipeline.close()
            self._pipeline = None
        if self._recorder is not None:
            await self._recorder.stop()
            self._recorder = None

    async def update_config(self, cfg: dict) -> dict:
        """热更新配置。无效配置抛 ValueError。需重建的标记 requires_restart。"""
        current = VoiceConfig.load()
        restart_needed = False
        for key, val in cfg.items():
            if not hasattr(current, key):
                raise ValueError(f"Unknown config key: {key}")
            if key == "vad_mode" and not (0 <= val <= 3):
                raise ValueError("vad_mode must be 0-3")
            if key == "min_confidence" and not (0.0 <= val <= 1.0):
                raise ValueError("min_confidence must be 0.0-1.0")
            setattr(current, key, val)
            if key in ("vad_mode", "sample_rate", "device_index", "asr"):
                restart_needed = True
        if restart_needed and self._running:
            await self.stop()
            await self.start()
        return {
            "applied": list(cfg.keys()),
            "requires_restart": restart_needed,
            "running": self._running,
        }

    async def get_transcriptions(self, limit: int = 50) -> list[dict]:
        """获取最近 limit 条转录历史。"""
        items = list(self._transcription_history)
        return items[-limit:]

    async def get_devices(self) -> list[dict]:
        """列出可用麦克风设备。"""
        import pyaudio

        devices: list[dict] = []
        p = pyaudio.PyAudio()
        try:
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if info.get("maxInputChannels", 0) > 0:
                    devices.append({
                        "index": i,
                        "name": info.get("name", f"Device {i}"),
                        "channels": info.get("maxInputChannels", 0),
                    })
        finally:
            p.terminate()
        return devices

    async def toggle_recording(self, start: bool) -> bool:
        """动态启停。当前通过 start/stop 实现。"""
        if start:
            return await self.start()
        await self.stop()
        return False
```

- [ ] **步骤 4：运行测试验证通过**

```bash
cd .worktrees/voice-refactor && uv run pytest tests/voice/test_service.py -v --timeout=10
```

- [ ] **步骤 5：Commit**

```bash
git add app/voice/service.py tests/voice/test_service.py
git commit -m "feat: add VoiceService class for voice lifecycle management"
```

---

### 任务 3：voice __init__ 导出 VoiceService

**文件：** `app/voice/__init__.py`

- [ ] **步骤 1：加导出**

```python
"""语音流水线：录音 → VAD → ASR → 文本输出。"""

from app.voice.pipeline import VoicePipeline as VoicePipeline
from app.voice.service import VoiceService as VoiceService
```

- [ ] **步骤 2：Commit**

```bash
git add app/voice/__init__.py
git commit -m "feat: export VoiceService from voice package"
```

---

### 任务 4：Lifespan 集成 VoiceService

**文件：** `app/api/main.py`

替换 `_init_voice_if_available()` + `_stop_voice()` 为 VoiceService。

- [ ] **步骤 1：修改 lifespan**

在 `app/api/main.py` 中：

1. 删除 `_init_voice_if_available` 函数（原行标记 `async def _init_voice_if_available`）
2. 删除 `_stop_voice` 函数（原行标记 `async def _stop_voice`）
3. 在 `from app.config import DATA_DIR` 附近加 `from app.voice import VoiceService`
4. lifespan 中 `voice_handle` 初始化替换为：

```python
voice_service = VoiceService()
app.state.voice_service = voice_service
if sched is not None:
    await voice_service.start(sched)
```

5. `yield` 后 `await _stop_voice(voice_handle)` 替换为：

```python
await voice_service.stop()
```

6. 在 `API_V1.include_router(ws_router...` 后加：

```python
from app.api.v1.voice import router as voice_router
API_V1.include_router(voice_router, prefix="/voice", tags=["voice"])
```

- [ ] **步骤 2：运行整体测试确保不破坏现有 API**

```bash
cd .worktrees/voice-refactor && uv run pytest tests/api/ -v --timeout=30 -x
```

若因 `voice_router` import 失败（该文件尚不存在），先建空 `app/api/v1/voice.py`：

```python
"""语音模块 REST 路由（占位，等待任务 5 实现）。"""

from fastapi import APIRouter

router = APIRouter(tags=["voice"])
```

- [ ] **步骤 3：Commit**

```bash
git add app/api/main.py app/api/v1/voice.py
git commit -m "refactor: integrate VoiceService into lifespan + register voice router placeholder"
```

---

### 任务 5：API 路由实现

**文件：** 新建 `app/api/v1/voice.py`（替换占位）+ 新建 `tests/api/test_voice_api.py`

- [ ] **步骤 1：写 API 测试**

`tests/api/test_voice_api.py`：

```python
"""v1 Voice API 测试."""

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


def test_voice_status(app_client: TestClient) -> None:
    """GET /api/v1/voice/status 返回运行状态."""
    resp = app_client.get("/api/v1/voice/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "enabled" in data
    assert "running" in data


def test_voice_config_get(app_client: TestClient) -> None:
    """GET /api/v1/voice/config 返回配置."""
    resp = app_client.get("/api/v1/voice/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "device_index" in data


def test_voice_start_stop(app_client: TestClient) -> None:
    """POST /api/v1/voice/start + stop 切换运行状态."""
    resp = app_client.post("/api/v1/voice/start")
    assert resp.status_code == 200
    resp = app_client.post("/api/v1/voice/stop")
    assert resp.status_code == 200


def test_voice_config_put(app_client: TestClient) -> None:
    """PUT /api/v1/voice/config 返回已应用的键列表。"""
    resp = app_client.put("/api/v1/voice/config", json={"device_index": 1})
    assert resp.status_code == 200
    data = resp.json()
    assert "applied" in data


def test_voice_config_put_invalid_returns_400(app_client: TestClient) -> None:
    """PUT /api/v1/voice/config 传无效 vad_mode 返 400。"""
    resp = app_client.put("/api/v1/voice/config", json={"vad_mode": 9})
    assert resp.status_code == 400
    data = resp.json()
    assert data["error"]["code"] == "INVALID_INPUT"


def test_voice_devices(app_client: TestClient) -> None:
    """GET /api/v1/voice/devices 返回列表（mock pyaudio）。"""
    from unittest.mock import patch
    with patch("app.voice.service.pyaudio.PyAudio") as MockPA:
        mock_pa = MockPA.return_value
        mock_pa.get_device_count.return_value = 2
        mock_pa.get_device_info_by_index.side_effect = [
            {"name": "Mic", "maxInputChannels": 1},
            {"name": "Speaker", "maxInputChannels": 0},
        ]
        resp = app_client.get("/api/v1/voice/devices")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["name"] == "Mic"
```

- [ ] **步骤 2：运行测试，预期部分失败（路由未注册）**

```bash
cd .worktrees/voice-refactor && uv run pytest tests/api/test_voice_api.py -v --timeout=10
```

- [ ] **步骤 3：实现路由**

`app/api/v1/voice.py`：

```python
"""语音模块 REST 路由。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
from app.voice.config import VoiceConfig
from app.voice.service import VoiceService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["voice"])


def _get_svc(request: Request) -> VoiceService:
    svc: VoiceService | None = getattr(request.app.state, "voice_service", None)
    if svc is None:
        raise RuntimeError("VoiceService not initialized")
    return svc


@router.get("/status")
async def voice_status(request: Request) -> dict:
    """当前语音运行状态。"""
    return _get_svc(request).status


@router.post("/start")
async def voice_start(request: Request) -> dict:
    """开启语音流水线。"""
    svc = _get_svc(request)
    if svc.status["running"]:
        return JSONResponse(
            status_code=409,
            content={"error": {"code": "ALREADY_RUNNING", "message": "Voice is already running"}},
        )
    ok = await svc.start()
    if not ok:
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "VOICE_DISABLED", "message": "Voice is disabled in config"}},
        )
    return {"status": "started"}


@router.post("/stop")
async def voice_stop(request: Request) -> dict:
    """停止语音流水线。"""
    await _get_svc(request).stop()
    return {"status": "stopped"}


@router.get("/config")
async def voice_config_get(request: Request) -> dict:
    """当前配置。"""
    from app.voice.config import VoiceConfig
    cfg = VoiceConfig.load()
    return {
        "enabled": cfg.enabled,
        "device_index": cfg.device_index,
        "sample_rate": cfg.sample_rate,
        "vad_mode": cfg.vad_mode,
        "min_confidence": cfg.min_confidence,
        "silence_timeout_ms": cfg.silence_timeout_ms,
    }


@router.put("/config")
async def voice_config_put(request: Request, body: dict) -> dict:
    """热更新配置。配置无效返 400。"""
    try:
        return await _get_svc(request).update_config(body)
    except ValueError as e:
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "INVALID_INPUT", "message": str(e)}},
        )


@router.get("/transcriptions")
async def voice_transcriptions(request: Request, limit: int = 50) -> list[dict]:
    """获取转录历史。"""
    return await _get_svc(request).get_transcriptions(limit=limit)


@router.get("/devices")
async def voice_devices(request: Request) -> list[dict]:
    """列出可用麦克风设备。"""
    return await _get_svc(request).get_devices()
```

- [ ] **步骤 4：运行测试验证通过**（路由已在任务 4 注册，`app.state.voice_service` 已注入）

```bash
cd .worktrees/voice-refactor && uv run pytest tests/api/test_voice_api.py -v --timeout=10
```

- [ ] **步骤 5：Commit**

```bash
git add app/api/v1/voice.py tests/api/test_voice_api.py
git commit -m "feat: add voice REST API endpoints"
```

---

### 任务 6：CLI 入口

**文件：** 新建 `app/voice/cli.py` + 新建 `app/voice/__main__.py`

- [ ] **步骤 1：实现 CLI**

`app/voice/cli.py`：

```python
"""语音模块 CLI 入口。"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from app.voice.service import VoiceService

logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="知行车秘 — 语音模块 CLI")
    parser.add_argument("--list-devices", action="store_true", help="列出可用麦克风设备")
    parser.add_argument("--device", type=int, default=None, help="麦克风设备索引")
    return parser.parse_args(argv)


async def _run_cli(args: argparse.Namespace) -> None:
    temp_svc = VoiceService()
    if args.list_devices:
        devices = await temp_svc.get_devices()
        if not devices:
            print("No input devices found.")
            return
        for d in devices:
            print(f"  {d['index']}: {d['name']} ({d['channels']} channels)")
        return

    def _print_transcription(text: str, confidence: float) -> None:
        print(f"[VAD:speech     ] {text} (conf={confidence:.2f})")

    cfg = VoiceConfig.load()
    if args.device is not None:
        devices = await temp_svc.get_devices()
        valid_indices = {d["index"] for d in devices}
        if args.device not in valid_indices:
            print(f"Error: device index {args.device} not found. Use --list-devices to see available devices.")
            sys.exit(1)
        cfg.device_index = args.device
    svc = VoiceService(config=cfg)
    ok = await svc.start(on_transcription=_print_transcription)
    if not ok:
        print("[WARN] Voice pipeline unavailable (ASR model/config disabled). Pipeline will run without transcription output.", file=sys.stderr)

    print("[INFO] Voice pipeline started. Press Ctrl+C to stop.")
    last_status = ""
    try:
        while True:
            st = svc.status
            vad = st.get("vad_status", "")
            if vad != last_status:
                print(f"[VAD:{vad:14s}]")
                last_status = vad
            await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        pass
    finally:
        await svc.stop()
        print("[INFO] Stopped.")


def main(argv: list[str] | None = None) -> None:
    """CLI 入口。"""
    args = _parse_args(argv)
    try:
        asyncio.run(_run_cli(args))
    except KeyboardInterrupt:
        pass
```

`app/voice/__main__.py`：

```python
"""python -m app.voice → CLI 入口。"""

from app.voice.cli import main

main()
```

- [ ] **步骤 2：试运行 CLI**

```bash
cd .worktrees/voice-refactor && uv run python -m app.voice --help
```

预期：打印 help 文本。

- [ ] **步骤 3：写 CLI 测试**

`tests/voice/test_cli.py`：

```python
"""测试 voice CLI 参数解析。"""

from app.voice.cli import _parse_args


def test_parse_args_defaults():
    """Given 无参数, When _parse_args(), Then list_devices=False, device=None."""
    args = _parse_args([])
    assert args.list_devices is False
    assert args.device is None


def test_parse_args_list_devices():
    """Given --list-devices, When _parse_args(), Then list_devices=True."""
    args = _parse_args(["--list-devices"])
    assert args.list_devices is True


def test_parse_args_device():
    """Given --device 1, When _parse_args(), Then device=1."""
    args = _parse_args(["--device", "1"])
    assert args.device == 1
```

- [ ] **步骤 4：运行 CLI 测试**

```bash
cd .worktrees/voice-refactor && uv run pytest tests/voice/test_cli.py -v --timeout=10
```

- [ ] **步骤 5：Commit**

```bash
git add app/voice/cli.py app/voice/__main__.py tests/voice/test_cli.py
git commit -m "feat: add voice CLI entry point + tests"
```

---

### 任务 7：独立语音服务

**文件：** 新建 `app/voice/server.py`

- [ ] **步骤 1：实现独立服务**

`app/voice/server.py`：

```python
"""独立语音 FastAPI 服务。不依赖 scheduler/memory/workflow。"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.voice import VoiceService

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

_WEBUI_DIR = Path(__file__).parent.parent.parent / "webui"


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    voice_service = VoiceService()
    _app.state.voice_service = voice_service
    await voice_service.start()
    yield
    await voice_service.stop()


app = FastAPI(title="知行车秘 — 语音服务", lifespan=_lifespan)

# 挂语音 API 路由
from app.api.v1.voice import router as voice_router
app.include_router(voice_router, prefix="/api/v1/voice")

# 静态文件
if _WEBUI_DIR.exists():
    app.mount("/static", StaticFiles(directory=_WEBUI_DIR), name="static")

    @app.get("/")
    async def root() -> FileResponse:
        return FileResponse(_WEBUI_DIR / "index.html")


def serve(host: str = "127.0.0.1", port: int = 34568) -> None:
    """启动独立语音服务。"""
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    serve()
    # 用法: uv run python -m app.voice.server
    # 也可: uv run python app/voice/server.py
```

- [ ] **步骤 2：验证服务可 import**

```bash
cd .worktrees/voice-refactor && uv run python -c "from app.voice.server import app; print('OK')"
```

预期：打印 OK。

- [ ] **步骤 3：创建启动脚本 `scripts/voice-server.sh`**（先 `mkdir -p scripts`）

```bash
#!/usr/bin/env bash
# 独立语音服务启动脚本
cd "$(dirname "$0")/.." || exit 1
exec uv run python -m app.voice.server "$@"
```

（若 `scripts/` 不存在则 `mkdir -p scripts`）

- [ ] **步骤 4：写独立服务集成测试**

`tests/voice/test_server.py`：

```python
"""测试独立语音服务。"""

from fastapi.testclient import TestClient

from app.voice.server import app


def test_server_status_returns_dict():
    """Given 独立服务 app, When GET /api/v1/voice/status, Then 200 + 含 enabled 字段。"""
    with TestClient(app) as c:
        resp = c.get("/api/v1/voice/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "enabled" in data


def test_server_voice_routes_registered():
    """Given 独立服务 app, When GET /api/v1/voice/config, Then 200。"""
    with TestClient(app) as c:
        resp = c.get("/api/v1/voice/config")
        assert resp.status_code == 200
```

- [ ] **步骤 5：运行集成测试**

```bash
cd .worktrees/voice-refactor && uv run pytest tests/voice/test_server.py -v --timeout=10
```

- [ ] **步骤 6：Commit**

```bash
git add app/voice/server.py scripts/voice-server.sh tests/voice/test_server.py
git commit -m "feat: add standalone voice server + run script + integration test"
```

---

### 任务 8：WebUI 语音控制台

**文件：** `webui/index.html` + `webui/app.js` + `webui/styles.css`

- [ ] **步骤 1：index.html 侧边栏加 tab 切换**

替换现有左侧面板 `.panel-left` 为 tab 模式：

```html
<div class="panel-left">
  <!-- Tab 导航 -->
  <div class="sidebar-tabs">
    <button class="tab-btn active" data-tab="simulate" onclick="switchTab('simulate')">驾驶模拟</button>
    <button class="tab-btn" data-tab="voice" onclick="switchTab('voice')">语音</button>
  </div>

  <!-- 驾驶模拟面板 -->
  <div id="panel-simulate" class="tab-panel active">
    <!-- 现有场景预设、驾驶员状态等全部内容 -->
  </div>

  <!-- 语音面板 -->
  <div id="panel-voice" class="tab-panel">
    <div class="section-title">录音控制</div>
    <div class="voice-controls">
      <button id="voiceRecordBtn" class="btn btn-success btn-sm" onclick="toggleVoiceRecording()">
        ● 开始录音
      </button>
      <span id="voiceStatusText" class="voice-status-text">未启动</span>
    </div>

    <div class="section-title">设备选择</div>
    <select id="voiceDeviceSelect" onchange="changeVoiceDevice(this.value)">
      <option value="">加载中...</option>
    </select>

    <div class="section-title">VAD 状态</div>
    <div id="voiceVadIndicator" class="vad-indicator idle">⚪ 空闲</div>

    <div class="section-title">配置</div>
    <details>
      <summary style="cursor:pointer;font-size:13px;color:#555;">展开配置</summary>
      <div class="voice-config-form">
        <div class="field">
          <label>VAD 模式 (0-3)</label>
          <input type="number" id="voiceVadMode" value="1" min="0" max="3">
        </div>
        <div class="field">
          <label>置信度阈值</label>
          <input type="number" id="voiceMinConfidence" value="0.5" min="0" max="1" step="0.1">
        </div>
        <button class="btn btn-secondary btn-sm" onclick="applyVoiceConfig()">应用</button>
      </div>
    </details>
  </div>
</div>

<!-- 右栏语音转录区（语音 tab 激活时显示） -->
<div id="panel-voice-right" class="tab-panel" style="display:none;">
  <div class="section-title">实时转录</div>
  <div id="voiceTranscriptionArea" class="voice-transcription-area">
    <span class="empty-hint">等待语音输入...</span>
  </div>
  <div class="section-title" style="margin-top:16px;">转录历史</div>
  <div id="voiceHistoryList" class="voice-history-list">
    <span class="empty-hint">暂无历史</span>
  </div>
</div>
```

右侧部分原 `.panel-right` 转为 `id="panel-simulate-right"`。

- [ ] **步骤 2：app.js 加语音控制逻辑**

```javascript
// ===== 语音控制台 =====
let _voicePollingTimer = null;
let _voiceTranscriptionTimer = null;
let _lastTranscriptionId = 0;

function switchTab(tab) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelector(`.tab-btn[data-tab="${tab}"]`).classList.add('active');
  document.querySelectorAll('.tab-panel').forEach(p => p.style.display = 'none');
  document.getElementById(`panel-${tab}`).style.display = 'block';
  document.getElementById(`panel-${tab}-right`).style.display = 'block';
  document.getElementById('panel-simulate-right').style.display = tab === 'simulate' ? 'block' : 'none';
  if (tab === 'voice') {
    startVoicePolling();
    loadVoiceDevices();
  } else {
    stopVoicePolling();
  }
}

function startVoicePolling() {
  stopVoicePolling();
  _voicePollingTimer = setInterval(pollVoiceStatus, 500);
  _voiceTranscriptionTimer = setInterval(pollVoiceTranscriptions, 1000);
  pollVoiceStatus();
  pollVoiceTranscriptions();
}

function stopVoicePolling() {
  if (_voicePollingTimer) { clearInterval(_voicePollingTimer); _voicePollingTimer = null; }
  if (_voiceTranscriptionTimer) { clearInterval(_voiceTranscriptionTimer); _voiceTranscriptionTimer = null; }
}

async function pollVoiceStatus() {
  try {
    const data = await api('GET', '/api/v1/voice/status');
    const running = data.running;
    const btn = document.getElementById('voiceRecordBtn');
    btn.textContent = running ? '■ 停止录音' : '● 开始录音';
    btn.className = running ? 'btn btn-secondary btn-sm' : 'btn btn-success btn-sm';
    document.getElementById('voiceStatusText').textContent = running ? '运行中' : '已停止';
    const vadEl = document.getElementById('voiceVadIndicator');
    const vadStatus = data.vad_status || 'idle';
    vadEl.className = `vad-indicator ${vadStatus}`;
    const labels = { idle: '⚪ 空闲', speech: '🟢 说话中', silence: '⚪ 静音' };
    vadEl.textContent = labels[vadStatus] || `⚪ ${vadStatus}`;
  } catch (e) { /* 静默 */ }
}

async function pollVoiceTranscriptions() {
  try {
    const items = await api('GET', `/api/v1/voice/transcriptions?limit=10`);
    if (!items || items.length === 0) return;
    const area = document.getElementById('voiceTranscriptionArea');
    area.innerHTML = items.slice(-3).reverse().map(t =>
      `<div class="transcription-item"><span class="trans-text">${escapeHtml(t.text)}</span><span class="trans-time">${new Date(t.timestamp).toLocaleTimeString()}</span></div>`
    ).join('');
    const history = document.getElementById('voiceHistoryList');
    history.innerHTML = items.slice().reverse().map(t =>
      `<div class="history-item"><span class="meta">${new Date(t.timestamp).toLocaleString()}</span> ${escapeHtml(t.text)}</div>`
    ).join('');
    // 滚动到底部
    area.scrollTop = area.scrollHeight;
  } catch (e) { /* 静默 */ }
}

async function toggleVoiceRecording() {
  try {
    const data = await api('GET', '/api/v1/voice/status');
    if (data.running) {
      await api('POST', '/api/v1/voice/stop');
    } else {
      await api('POST', '/api/v1/voice/start');
    }
    pollVoiceStatus();
  } catch (e) {
    showToast('录音控制失败: ' + e.message, 'error');
  }
}

async function loadVoiceDevices() {
  try {
    const devices = await api('GET', '/api/v1/voice/devices');
    const sel = document.getElementById('voiceDeviceSelect');
    sel.innerHTML = '<option value="">-- 选择设备 --</option>';
    devices.forEach(d => {
      const opt = document.createElement('option');
      opt.value = d.index;
      opt.textContent = `${d.name} (${d.channels} ch)`;
      sel.appendChild(opt);
    });
  } catch (e) {
    document.getElementById('voiceDeviceSelect').innerHTML = '<option value="">设备加载失败</option>';
  }
}

async function changeVoiceDevice(index) {
  if (!index) return;
  try {
    await api('PUT', '/api/v1/voice/config', { device_index: parseInt(index) });
    showToast('设备已切换，请重新开始录音', 'info');
  } catch (e) {
    showToast('设备切换失败: ' + e.message, 'error');
  }
}

async function applyVoiceConfig() {
  const vadMode = parseInt(document.getElementById('voiceVadMode').value);
  const minConf = parseFloat(document.getElementById('voiceMinConfidence').value);
  try {
    await api('PUT', '/api/v1/voice/config', { vad_mode: vadMode, min_confidence: minConf });
    showToast('配置已应用', 'success');
  } catch (e) {
    showToast('配置应用失败: ' + e.message, 'error');
  }
}
```

- [ ] **步骤 3：styles.css 加语音面板样式**

```css
/* 侧边栏 tab */
.sidebar-tabs { display: flex; border-bottom: 2px solid #e0e0e0; margin-bottom: 12px; }
.tab-btn { flex: 1; padding: 8px; border: none; background: none; cursor: pointer; font-size: 13px; font-weight: 500; color: #888; transition: all .2s; }
.tab-btn.active { color: #007bff; border-bottom: 2px solid #007bff; margin-bottom: -2px; }
.tab-btn:hover { color: #555; }
.tab-panel { display: none; }
.tab-panel.active { display: block; }

/* 语音控制 */
.voice-controls { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.voice-status-text { font-size: 12px; color: #888; }
.vad-indicator { padding: 6px 10px; border-radius: 4px; font-size: 13px; margin-bottom: 10px; }
.vad-indicator.idle { background: #f0f0f0; color: #888; }
.vad-indicator.speech { background: #d4edda; color: #155724; }
.vad-indicator.silence { background: #f0f0f0; color: #888; }
.voice-config-form { padding: 8px 0; }

/* 转录区域 */
.voice-transcription-area {
  background: #fafafa;
  border: 1px solid #e8e8e8;
  border-radius: 6px;
  padding: 12px;
  min-height: 120px;
  max-height: 300px;
  overflow-y: auto;
}
.transcription-item {
  padding: 6px 0;
  border-bottom: 1px solid #eee;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.transcription-item:last-child { border-bottom: none; }
.trans-text { font-size: 14px; font-weight: 500; color: #333; }
.trans-time { font-size: 11px; color: #999; }
.voice-history-list { max-height: 300px; overflow-y: auto; }
```

- [ ] **步骤 4：Commit**

```bash
git add webui/index.html webui/app.js webui/styles.css
git commit -m "feat: add voice console tab to WebUI"
```

---

### 任务 9：文档同步 + 最终验证

需同步的文档：
- `AGENTS.md`：文件结构表加 `service.py`；系统设计 mermaid 图 VoiceService 替代裸 Pipeline
- `app/voice/AGENTS.md`：加 `service.py` 说明，更新测试覆盖描述
- `app/api/AGENTS.md`：组件表加 `v1/voice.py`，端点表加语音路由

- [ ] **步骤 0：同步 AGENTS.md** — 更新上述文件反映新模块结构

- [ ] **步骤 1：ruff check**

```bash
cd .worktrees/voice-refactor && uv run ruff check --fix
```

- [ ] **步骤 2：ruff format**

```bash
cd .worktrees/voice-refactor && uv run ruff format
```

- [ ] **步骤 3：ty check**

```bash
cd .worktrees/voice-refactor && uv run ty check
```

- [ ] **步骤 4：全量 pytest**

```bash
cd .worktrees/voice-refactor && uv run pytest --timeout=30
```

- [ ] **步骤 5：提交所有未 commit 变更**

```bash
cd .worktrees/voice-refactor && git add -A && git status
```

- [ ] **步骤 6：提交全部剩余变更**

```bash
cd .worktrees/voice-refactor && git commit -m "chore: finalize voice module refactor"
```
