"""VoicePipeline 编排：VAD → ASR → 文本输出。"""

from __future__ import annotations

import asyncio
import logging
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

from app.voice.asr import ASREngine, SherpaOnnxASREngine
from app.voice.constants import _FRAME_BYTES, VADStatus
from app.voice.vad import VADEngine

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path("config/voice.toml")


def _load_asr_config() -> dict:
    """从 voice.toml 读取 ASR 配置。"""
    try:
        with _CONFIG_PATH.open("rb") as f:
            data = tomllib.load(f)
        return data.get("voice", {}).get("asr", {})
    except OSError, tomllib.TOMLDecodeError:
        logger.warning("Failed to read %s, using defaults", _CONFIG_PATH)
        return {}


def _load_voice_config() -> dict:
    """从 voice.toml 读取顶层语音配置。"""
    try:
        with _CONFIG_PATH.open("rb") as f:
            data = tomllib.load(f)
        return data.get("voice", {})
    except OSError, tomllib.TOMLDecodeError:
        return {}


class VoicePipeline:
    """VAD → ASR 编排。yield 逐条转录结果。"""

    def __init__(
        self,
        vad_mode: int | None = None,
        sample_rate: int | None = None,
        min_confidence: float | None = None,
        asr_engine: ASREngine | None = None,
        on_transcription: Callable[[str, float], None] | None = None,
    ) -> None:
        """初始化语音流水线。参数未传时从 config/voice.toml 读取。"""
        cfg = _load_voice_config()
        if vad_mode is None:
            vad_mode = cfg.get("vad_mode", 1)
        if sample_rate is None:
            sample_rate = cfg.get("sample_rate", 16000)
        if min_confidence is None:
            min_confidence = cfg.get("min_confidence", 0.5)
        silence_ms = cfg.get("silence_timeout_ms", 500)
        silence_frames = max(1, silence_ms // 30)

        self._vad = VADEngine(
            mode=vad_mode,
            sample_rate=sample_rate,
            silence_timeout_frames=silence_frames,
        )
        if asr_engine is None:
            asr_cfg = _load_asr_config()
            model_path = asr_cfg.get("model", "data/models/sense_voice/model.int8.onnx")
            tokens_path = asr_cfg.get("tokens", "data/models/sense_voice/tokens.txt")
            num_threads = asr_cfg.get("num_threads", 2)
            language = asr_cfg.get("language", "zh")
            use_itn = asr_cfg.get("use_itn", True)
            if Path(model_path).exists() and Path(tokens_path).exists():
                asr_engine = SherpaOnnxASREngine(
                    model_path,
                    tokens_path,
                    num_threads=num_threads,
                    language=language,
                    use_itn=use_itn,
                )
            else:
                asr_engine = SherpaOnnxASREngine("", "")
        self._asr = asr_engine
        self._min_confidence = min_confidence
        self._on_transcription = on_transcription
        self._audio_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._running = False

    async def feed_audio(self, chunk: bytes) -> None:
        """从麦克风/recorder 喂入音频数据。"""
        await self._audio_queue.put(chunk)

    async def run(self) -> AsyncIterator[str]:
        """主循环：读取音频 → VAD 切分 → ASR 转录。yield 高置信度文本。"""
        self._running = True
        buffer = bytearray()

        while self._running:
            chunk = await self._audio_queue.get()
            if len(chunk) != _FRAME_BYTES:
                logger.warning(
                    "Dropping audio chunk: expected %d bytes, got %d",
                    _FRAME_BYTES,
                    len(chunk),
                )
                continue

            status = self._vad.process_frame(chunk)
            if status is VADStatus.SPEECH_START:
                buffer = bytearray(chunk)
            elif status is VADStatus.SPEECH:
                buffer.extend(chunk)
            elif status is VADStatus.SPEECH_END:
                if len(buffer) > _FRAME_BYTES:
                    result = await self._asr.transcribe(bytes(buffer))
                    if result.text and result.confidence >= self._min_confidence:
                        if self._on_transcription:
                            self._on_transcription(result.text, result.confidence)
                        yield result.text
                buffer = bytearray()

    async def stop(self) -> None:
        """停止主循环."""
        self._running = False

    async def close(self) -> None:
        """停止并释放 ASR 资源."""
        await self.stop()
        await self._asr.close()
