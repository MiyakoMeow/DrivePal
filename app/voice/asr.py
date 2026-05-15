"""ASR 引擎抽象 + sherpa-onnx 实现。"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


_onnx_lib_setup_done: list[bool] = [False]


def _ensure_onnx_lib() -> None:
    """确保 sherpa-onnx 能加载 onnxruntime 共享库。

    sherpa-onnx 的 .so 依赖 libonnxruntime.so，但后者不在标准库路径中。
    此处用两种方式解决：
    1. 在 sherpa-onnx 的 lib/ 目录下创建符号链接
    2. 用 ctypes 预加载库（兜底）

    此函数幂等，仅首次调用时执行。
    """
    if _onnx_lib_setup_done[0]:
        return

    import importlib.util

    if importlib.util.find_spec("onnxruntime") is None:
        logger.warning("onnxruntime not installed, ASR unavailable")
        _onnx_lib_setup_done[0] = True
        return

    onnx_lib = _find_onnx_lib()
    if onnx_lib is None:
        _onnx_lib_setup_done[0] = True
        return

    _create_onnx_symlink(onnx_lib)

    try:
        import ctypes

        ctypes.CDLL(str(onnx_lib.resolve()), mode=ctypes.RTLD_GLOBAL)
        logger.debug("Preloaded onnxruntime via ctypes.RTLD_GLOBAL")
    except OSError as e:
        logger.warning("Failed to preload onnxruntime: %s", e)

    _onnx_lib_setup_done[0] = True


def _find_onnx_lib() -> Path | None:
    """定位 onnxruntime 的共享库路径。"""
    import onnxruntime

    ort_capi = Path(onnxruntime.__file__).parent / "capi"
    lib_name = "libonnxruntime.so"
    onnx_lib = ort_capi / lib_name

    if onnx_lib.exists():
        return onnx_lib

    candidates = sorted(ort_capi.glob("libonnxruntime.so.*"), reverse=True)
    if candidates:
        return candidates[0]

    logger.warning("libonnxruntime.so not found at %s", ort_capi)
    return None


def _create_onnx_symlink(onnx_lib: Path) -> None:
    """在 sherpa-onnx 的 lib/ 下建立 libonnxruntime.so 符号链接。"""
    lib_dir = None
    try:
        from importlib.metadata import files as pkg_files

        pkg = "sherpa_onnx"
        found = pkg_files(pkg)
        if found is not None:
            for f in found:
                p = Path(f.locate())
                if "_sherpa_onnx" in p.name and p.suffix == ".so":
                    lib_dir = p.parent
                    break
    except ImportError, TypeError, OSError:
        pass

    if lib_dir is None or not lib_dir.is_dir():
        return

    target = lib_dir / "libonnxruntime.so"
    if target.exists():
        return

    try:
        target.symlink_to(onnx_lib.resolve())
        logger.info("Created symlink: %s → %s", target, onnx_lib)
    except OSError as e:
        logger.warning("Failed to create symlink: %s", e)


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
        """转录音频为文本。audio_bytes 为 16kHz 16bit PCM mono。"""

    @abstractmethod
    async def close(self) -> None:
        """释放资源."""


class SherpaOnnxASREngine(ASREngine):
    """sherpa-onnx 离线 ASR 引擎（SenseVoice 模型）。"""

    def __init__(
        self,
        model_path: str,
        tokens_path: str,
        *,
        num_threads: int = 2,
        language: str = "zh",
        use_itn: bool = True,
    ) -> None:
        """初始化 sherpa-onnx ASR 引擎。

        Args:
            model_path: SenseVoice ONNX 模型路径。
            tokens_path: tokens.txt 路径。
            num_threads: 推理线程数。
            language: 语言（zh/en/ja/ko/yue）。
            use_itn: 是否使用逆文本正则化（数字/日期格式化）。

        """
        self._model_path = model_path
        self._tokens_path = tokens_path
        self._num_threads = num_threads
        self._language = language
        self._use_itn = use_itn
        self._recognizer = None
        self._sample_rate = 16000

    async def _ensure_loaded(self) -> None:
        """延迟加载 recognizer。"""
        if self._recognizer is not None:
            return
        if not self._model_path or not self._tokens_path:
            logger.warning("ASR model paths not configured, returning empty results")
            self._recognizer = "unavailable"
            return
        if not Path(self._model_path).exists():
            logger.warning("ASR model not found: %s", self._model_path)
            self._recognizer = "unavailable"
            return
        _ensure_onnx_lib()
        import sherpa_onnx

        logger.info(
            "Loading ASR model: %s (threads=%d, lang=%s)",
            self._model_path,
            self._num_threads,
            self._language,
        )
        self._recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=self._model_path,
            tokens=self._tokens_path,
            num_threads=self._num_threads,
            use_itn=self._use_itn,
            language=self._language,
        )
        logger.info("ASR model loaded")

    async def transcribe(self, audio_bytes: bytes) -> ASRResult:
        """转录音频。audio_bytes：16kHz 16bit PCM mono。"""
        await self._ensure_loaded()
        if not audio_bytes:
            return ASRResult(text="", confidence=0.0)
        if self._recognizer == "unavailable":
            return ASRResult(text="", confidence=0.0)

        # 转换 PCM int16 → float32 (归一化到 [-1, 1])
        samples = (
            np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        )
        if len(samples) == 0:
            return ASRResult(text="", confidence=0.0)

        stream = self._recognizer.create_stream()
        stream.accept_waveform(self._sample_rate, samples)
        self._recognizer.decode_stream(stream)
        result = stream.result
        text = (result.text or "").strip()

        # SenseVoice 不直接输出数值置信度。
        # 有文本时设为 0.9（经验值），空文本为 0.0
        confidence = 0.9 if text else 0.0
        return ASRResult(text=text, confidence=confidence, is_final=True)

    async def close(self) -> None:
        """释放 recognizer。"""
        self._recognizer = None
        logger.info("ASR engine closed")
