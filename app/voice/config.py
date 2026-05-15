"""语音流水线配置."""

import logging
from dataclasses import dataclass, field

from app.config import ensure_config, get_config_root

logger = logging.getLogger(__name__)


@dataclass
class VoiceConfig:
    """语音流水线配置，含 VAD/ASR 参数。缺省值与 voice.toml 默认一致。"""

    device_index: int = 0
    sample_rate: int = 16000
    vad_mode: int = 1
    min_confidence: float = 0.5
    silence_timeout_ms: int = 500
    asr: dict | None = field(
        default_factory=lambda: {
            "model": "data/models/sense_voice/model.int8.onnx",
            "tokens": "data/models/sense_voice/tokens.txt",
            "num_threads": 2,
            "language": "zh",
            "use_itn": True,
        }
    )

    @classmethod
    def _toml_defaults(cls) -> dict:
        """从 dataclass 默认值生成 TOML dict。默认值唯一来源为字段默认。"""
        cfg = cls()
        return {
            "voice": {
                "device_index": cfg.device_index,
                "sample_rate": cfg.sample_rate,
                "vad_mode": cfg.vad_mode,
                "min_confidence": cfg.min_confidence,
                "silence_timeout_ms": cfg.silence_timeout_ms,
                "asr": cfg.asr,
            },
        }

    @classmethod
    def load(cls) -> VoiceConfig:
        """加载 voice.toml，文件缺失则自动生成。"""
        path = get_config_root() / "voice.toml"
        raw = ensure_config(path, cls._toml_defaults())
        voice_data = raw.get("voice", {})
        asr_data = voice_data.get("asr")
        if isinstance(asr_data, dict) and not asr_data:
            logger.warning(
                "Empty [voice.asr] section in %s, using built-in defaults", path
            )
        return cls(
            device_index=voice_data.get("device_index", cls.device_index),
            sample_rate=voice_data.get("sample_rate", cls.sample_rate),
            vad_mode=voice_data.get("vad_mode", cls.vad_mode),
            min_confidence=voice_data.get("min_confidence", cls.min_confidence),
            silence_timeout_ms=voice_data.get(
                "silence_timeout_ms", cls.silence_timeout_ms
            ),
            # cls.asr 在 dataclass 上返回 Field descriptor（因使用 default_factory）
            # 需用 cls().asr 取实例默认值。同时避免空 dict {} 通过
            asr=asr_data if isinstance(asr_data, dict) and asr_data else cls().asr,
        )
