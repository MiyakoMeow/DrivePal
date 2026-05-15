"""语音活动检测。封装 webrtcvad，切分语音段。"""

import logging

import webrtcvad

logger = logging.getLogger(__name__)


class VADEngine:
    """VAD 引擎，检测语音起止并切分。"""

    def __init__(self, mode: int = 1, sample_rate: int = 16000) -> None:
        """初始化 VAD 引擎."""
        self._vad = webrtcvad.Vad(mode)
        self._sample_rate = sample_rate
        self._frame_ms = 30
        self._frame_bytes = int(sample_rate * 2 * self._frame_ms / 1000)
        self._silence_frames = 0
        self._speech_frames = 0
        self._silence_timeout_frames = 17

    def is_speech(self, audio_chunk: bytes) -> bool:
        """检测音频帧是否包含语音."""
        if len(audio_chunk) != self._frame_bytes:
            return False
        return self._vad.is_speech(audio_chunk, self._sample_rate)

    def reset(self) -> None:
        """重置语音/静音帧计数."""
        self._speech_frames = 0
        self._silence_frames = 0

    def process_frame(self, audio_chunk: bytes) -> str | None:
        """返回 'speech_start'/'speech_end'/'silence'/'speech' 或 None。"""
        speech = self.is_speech(audio_chunk)
        if speech:
            self._speech_frames += 1
            self._silence_frames = 0
            if self._speech_frames == 1:
                return "speech_start"
            return "speech"
        self._silence_frames += 1
        if (
            self._speech_frames > 0
            and self._silence_frames > self._silence_timeout_frames
        ):
            self.reset()
            return "speech_end"
        return "silence"
