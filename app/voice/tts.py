"""TTS 客户端——edge-tts 封装，静默降级."""

import asyncio
import hashlib
import logging
import time
import uuid

from app.voice.config import VoiceConfig

logger = logging.getLogger(__name__)

_MAX_CACHE_ENTRIES = 50
_CACHE_TTL_SECONDS = 60


class TTSClient:
    """edge-tts 封装，合成文本为 MP3 字节。失败静默降级返 None。"""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[bytes, float]] = {}
        self._cache_lock = asyncio.Lock()
        self._voice = "zh-CN-XiaoxiaoNeural"

    def _prune_cache(self) -> None:
        now = time.monotonic()
        expired = [
            k for k, (_, ts) in self._cache.items() if now - ts > _CACHE_TTL_SECONDS
        ]
        for k in expired:
            del self._cache[k]

    def _evict_lru(self) -> None:
        while len(self._cache) > _MAX_CACHE_ENTRIES:
            oldest_key = min(self._cache, key=lambda k: self._cache[k][1])
            del self._cache[oldest_key]

    async def synthesize(self, text: str) -> bytes | None:
        """合成文本为 MP3 字节。失败返 None。"""
        if not text.strip():
            return None

        key_material = f"{self._voice}:{text}"
        text_hash = hashlib.sha256(key_material.encode()).hexdigest()

        async with self._cache_lock:
            self._prune_cache()
            if text_hash in self._cache:
                mp3_bytes, _ = self._cache[text_hash]
                self._cache[text_hash] = (mp3_bytes, time.monotonic())
                return mp3_bytes

        output_path = f"/tmp/drivepal_tts_{uuid.uuid4()}.mp3"
        try:
            proc = await asyncio.create_subprocess_exec(
                "edge-tts",
                "--voice",
                self._voice,
                "--text",
                text,
                "--write-media",
                output_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                await asyncio.wait_for(proc.communicate(), timeout=30.0)
            except TimeoutError:
                logger.warning("edge-tts timed out after 30s")
                proc.kill()
                await proc.wait()
            if proc.returncode != 0:
                logger.warning("edge-tts exited with code %d", proc.returncode)
                return None

            with open(output_path, "rb") as f:
                mp3_bytes = f.read()

            if mp3_bytes:
                async with self._cache_lock:
                    self._cache[text_hash] = (mp3_bytes, time.monotonic())
                    self._evict_lru()

            return mp3_bytes or None
        except FileNotFoundError:
            logger.warning("edge-tts not installed, TTS unavailable")
            return None
        except Exception:
            logger.warning("TTS synthesis failed", exc_info=True)
            return None
        finally:
            try:
                import os

                os.unlink(output_path)
            except OSError:
                pass

    @property
    def voice(self) -> str:
        """当前 TTS 语音名称（如 zh-CN-XiaoxiaoNeural）。"""
        return self._voice

    @voice.setter
    def voice(self, value: str) -> None:
        self._voice = value


_tts_client: TTSClient | None = None


def get_tts_client() -> TTSClient:
    """获取模块级 TTSClient 单例，按需创建。"""
    global _tts_client
    if _tts_client is None:
        cfg = VoiceConfig.load()
        _tts_client = TTSClient()
        _tts_client.voice = cfg.tts_voice
    return _tts_client
