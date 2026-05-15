"""VoiceService — 语音服务生命周期封装。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import deque
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.scheduler import ProactiveScheduler

from app.voice.config import VoiceConfig
from app.voice.pipeline import VoicePipeline
from app.voice.recorder import VoiceRecorder

logger = logging.getLogger(__name__)

_HISTORY_MAXLEN = 200
_MAX_VAD_MODE = 3


class VoiceService:
    """封装 VoicePipeline + VoiceRecorder 生命周期。提供统一启停/状态/配置接口。"""

    def __init__(self, config: VoiceConfig | None = None) -> None:
        cfg = config or VoiceConfig.load()
        self._enabled = cfg.enabled
        self._pipeline: VoicePipeline | None = None
        self._recorder: VoiceRecorder | None = None
        self._consume_task: asyncio.Task | None = None
        self._fire_tasks: set[asyncio.Task] = set()
        self._fire_task_limit = 5
        self._running = False
        self._sched: ProactiveScheduler | None = None
        self._on_transcription_external: Callable[[str, float], None] | None = None
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

        self._sched = sched
        self._on_transcription_external = on_transcription

        try:
            pipeline = VoicePipeline(on_transcription=self._handle_transcription)
            recorder = VoiceRecorder()
            await recorder.start(pipeline)
        except Exception:
            logger.warning("Voice service start failed", exc_info=True)
            await self._cleanup()
            return False
        else:

            async def _consume() -> None:
                async for _ in pipeline.run():
                    pass

            task = asyncio.create_task(_consume())
            self._pipeline = pipeline
            self._recorder = recorder
            self._consume_task = task
            self._running = True
            logger.info("Voice service started")
            return True

    def _handle_transcription(self, text: str, confidence: float) -> None:
        """内部回调：写历史 + 可选转发 scheduler + 可选外部回调。"""
        self._transcription_history.append(
            {
                "text": text,
                "confidence": confidence,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if self._sched is not None:
            if len(self._fire_tasks) >= self._fire_task_limit:
                logger.debug("Fire tasks at limit, dropping voice text: %.30s", text)
                return
            task = asyncio.create_task(self._sched.push_voice_text(text))
            self._fire_tasks.add(task)
            task.add_done_callback(self._fire_tasks.discard)
        if self._on_transcription_external is not None:
            try:
                self._on_transcription_external(text, confidence)
            except Exception:
                logger.exception("External on_transcription callback failed")

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
            with contextlib.suppress(asyncio.CancelledError):
                await self._consume_task
            self._consume_task = None
        if self._fire_tasks:
            for t in list(self._fire_tasks):
                t.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.gather(*self._fire_tasks, return_exceptions=True)
            self._fire_tasks.clear()
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
                msg = f"Unknown config key: {key}"
                raise ValueError(msg)
            if key == "vad_mode" and not (0 <= val <= _MAX_VAD_MODE):
                msg = "vad_mode must be 0-3"
                raise ValueError(msg)
            if key == "min_confidence" and not (0.0 <= val <= 1.0):
                msg = "min_confidence must be 0.0-1.0"
                raise ValueError(msg)
            setattr(current, key, val)
            if key in ("vad_mode", "sample_rate", "device_index", "asr"):
                restart_needed = True
        if restart_needed and self._running:
            saved_sched = self._sched
            saved_cb = self._on_transcription_external
            await self.stop()
            await self.start(sched=saved_sched, on_transcription=saved_cb)
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
                    devices.append(
                        {
                            "index": i,
                            "name": info.get("name", f"Device {i}"),
                            "channels": info.get("maxInputChannels", 0),
                        }
                    )
        finally:
            p.terminate()
        return devices

    async def toggle_recording(self, *, start: bool) -> bool:
        """动态启停。"""
        if start:
            return await self.start()
        await self.stop()
        return False
