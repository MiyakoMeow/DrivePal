"""VoiceService — 语音服务生命周期封装。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import deque
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import tomli_w

from app.config import get_config_root

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
        self._config = config or VoiceConfig.load()
        self._enabled = self._config.enabled
        self._pipeline: VoicePipeline | None = None
        self._recorder: VoiceRecorder | None = None
        self._consume_task: asyncio.Task | None = None
        self._fire_tasks: set[asyncio.Task] = set()
        self._fire_task_limit = 5  # 并发推送 scheduler 上限，超限丢弃防止积压
        self._running = False
        self._sched: ProactiveScheduler | None = None
        self._on_transcription_external: Callable[[str, float], None] | None = None
        self._transcription_history: deque[dict] = deque(maxlen=_HISTORY_MAXLEN)
        self._vad_status: str = "idle"

    @property
    def status(self) -> dict:
        """当前运行状态。"""
        c = self._config
        return {
            "enabled": self._enabled,
            "running": self._running,
            "vad_status": self._vad_status,
            "config": {
                "device_index": c.device_index,
                "sample_rate": c.sample_rate,
                "vad_mode": c.vad_mode,
                "min_confidence": c.min_confidence,
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

        if sched is not None:
            self._sched = sched
        if on_transcription is not None:
            self._on_transcription_external = on_transcription

        try:
            pipeline = VoicePipeline(
                on_transcription=self._handle_transcription,
                on_vad_status=lambda s: setattr(self, "_vad_status", s),
            )
            self._pipeline = pipeline  # 提前赋值，防 start 失败时泄漏
            recorder = VoiceRecorder(device_index=self._config.device_index)
            self._recorder = recorder
            await recorder.start(pipeline)
        except Exception:
            logger.warning("Voice service start failed", exc_info=True)
            await self._cleanup()
            return False
        else:
            # consume 丢弃 yield 值：转录文本已由 _handle_transcription 回调处理
            async def _consume() -> None:
                try:
                    async for _ in pipeline.run():
                        pass
                except Exception:
                    logger.exception("Voice pipeline consume failed, stopping")
                    self._running = False
                    self._consume_task = None  # 防 self-cancel
                    await self._cleanup()

            task = asyncio.create_task(_consume())
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
            # 同步回调中不可 await，用 set 大小做并发限流。
            # task 完成后 done_callback 自动 discard，单线程下无竞态
            if len(self._fire_tasks) >= self._fire_task_limit:
                logger.debug("Fire tasks at limit, dropping voice text: %.30s", text)
                return

            sched = self._sched

            async def _push(text: str) -> None:
                try:
                    await sched.push_voice_text(text)
                except Exception:
                    logger.exception("Failed to push voice text to scheduler")

            task = asyncio.create_task(_push(text))
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
        """清理内部资源。各步骤独立 try/except 防泄漏。"""
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
            try:
                await self._pipeline.close()
            except Exception:
                logger.exception("Pipeline close failed")
            self._pipeline = None
        if self._recorder is not None:
            try:
                await self._recorder.stop()
            except Exception:
                logger.exception("Recorder stop failed")
            self._recorder = None

    async def update_config(self, cfg: dict) -> dict:
        """热更新配置。无效配置抛 ValueError。先全体验证再统一应用。"""
        # 第一阶段：全体验证
        validated: list[tuple[str, object]] = []
        for key, val in cfg.items():
            if not hasattr(self._config, key):
                msg = f"Unknown config key: {key}"
                raise ValueError(msg)
            if key == "vad_mode" and not (0 <= val <= _MAX_VAD_MODE):
                msg = "vad_mode must be 0-3"
                raise ValueError(msg)
            if key == "min_confidence" and not (0.0 <= val <= 1.0):
                msg = "min_confidence must be 0.0-1.0"
                raise ValueError(msg)
            validated.append((key, val))
        # 第二阶段：统一应用
        restart_needed = False
        for key, val in validated:
            setattr(self._config, key, val)
            if key == "enabled":
                self._enabled = bool(val)
            if key in (
                "vad_mode",
                "sample_rate",
                "device_index",
                "asr",
                "min_confidence",
                "silence_timeout_ms",
            ):
                restart_needed = True
        # 持久化到 TOML 文件
        try:
            path = get_config_root() / "voice.toml"
            c = self._config
            raw_voice: dict = {
                "enabled": c.enabled,
                "device_index": c.device_index,
                "sample_rate": c.sample_rate,
                "vad_mode": c.vad_mode,
                "min_confidence": c.min_confidence,
                "silence_timeout_ms": c.silence_timeout_ms,
            }
            if c.asr is not None:
                raw_voice["asr"] = c.asr
            raw: dict = {"voice": raw_voice}

            def _write_config() -> None:
                with path.open("wb") as f:
                    tomli_w.dump(raw, f)

            await asyncio.to_thread(_write_config)
        except (OSError, TypeError, ValueError) as e:
            logger.warning("Failed to persist config: %s", e)
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
        try:
            import pyaudio
        except ImportError:
            logger.warning("pyaudio not available, cannot list devices")
            return []

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
