"""语音流水线共享常量。"""

from enum import StrEnum

_SAMPLE_RATE = 16000
_FRAMES_PER_CHUNK = 480


class VADStatus(StrEnum):
    """VAD 帧状态枚举。"""

    SPEECH_START = "speech_start"
    SPEECH = "speech"
    SPEECH_END = "speech_end"
    SILENCE = "silence"
