"""ASR 引擎抽象 + sherpa-onnx 实现。"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ASRResult:
    """ASR 转录结果."""

    text: str = ""
    confidence: float = 0.0
    is_final: bool = True


class ASREngine(ABC):
    """ASR 引擎抽象基类."""

    @abstractmethod
    async def transcribe(self, audio_bytes: bytes) -> ASRResult:
        """转录音频为文本."""

    @abstractmethod
    async def close(self) -> None:
        """释放资源."""


class SherpaOnnxASREngine(ASREngine):
    """sherpa-onnx 本地 ASR。当前返回占位空文本。"""

    def __init__(self, model_path: str = "", tokens_path: str = "") -> None:
        """初始化 sherpa-onnx 引擎."""
        self._model_path = model_path
        self._tokens_path = tokens_path
        self._recognizer = None

    async def transcribe(self, audio_bytes: bytes) -> ASRResult:
        """转录音频."""
        return ASRResult(text="", confidence=0.0, is_final=True)

    async def close(self) -> None:
        """释放资源."""
        self._recognizer = None
