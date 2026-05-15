"""麦克风录音模块。pyaudio 封装。"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.voice.pipeline import VoicePipeline

from app.voice.constants import _FRAME_BYTES, _SAMPLE_RATE

logger = logging.getLogger(__name__)

_CHANNELS = 1
_FORMAT = 8


class VoiceRecorder:
    """pyaudio 麦克风录音。持续录音 → 30ms 帧 → feed VoicePipeline。"""

    def __init__(self, device_index: int = 0) -> None:
        """初始化录音器."""
        self._device_index = device_index
        self._running = False

    async def start(self, pipeline: VoicePipeline) -> None:
        """启动录音。在线程池运行 pyaudio 阻塞循环。"""
        self._running = True

        def _record_loop(loop: asyncio.AbstractEventLoop) -> None:
            import pyaudio

            p = pyaudio.PyAudio()
            stream = None
            try:
                stream = p.open(
                    format=_FORMAT,
                    channels=_CHANNELS,
                    rate=_SAMPLE_RATE,
                    input=True,
                    input_device_index=self._device_index,
                    frames_per_buffer=_FRAME_BYTES,
                )
                while self._running:
                    data = stream.read(_FRAME_BYTES // 2, exception_on_overflow=False)
                    asyncio.run_coroutine_threadsafe(
                        pipeline.feed_audio(data),
                        loop,
                    )
            finally:
                if stream is not None:
                    stream.stop_stream()
                    stream.close()
                p.terminate()

        loop = asyncio.get_running_loop()
        self._task = loop.run_in_executor(None, _record_loop, loop)

    async def stop(self) -> None:
        """停止录音."""
        self._running = False
        if hasattr(self, "_task"):
            self._task.cancel()
