"""弹性 embedding 封装，对标 LlmClient。"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.embedding import EmbeddingModel

logger = logging.getLogger(__name__)


_SLEEP = asyncio.sleep

_TRANSIENT_PATTERNS = (
    "connection",
    "timeout",
    "rate limit",
    "eof",
    "reset",
    "service unavailable",
    "bad gateway",
    "internal server error",
)


def _is_transient(exc: Exception) -> bool:
    err = str(exc).lower()
    return any(p in err for p in _TRANSIENT_PATTERNS)


class EmbeddingClient:
    """EmbeddingModel 的弹性封装，提供批量编码和指数退避重试。"""

    MAX_RETRIES = 5
    BACKOFF_BASE = 2
    BATCH_SIZE = 100

    def __init__(
        self,
        embedding_model: EmbeddingModel,
        *,
        rng: random.Random | None = None,
    ) -> None:
        """初始化 EmbeddingClient。"""
        self._model = embedding_model
        self._rng = rng if rng is not None else random.Random()
        self._has_batch = hasattr(embedding_model, "batch_encode")

    async def encode(self, text: str) -> list[float]:
        """编码单条，委托给 encode_batch。"""
        return (await self.encode_batch([text]))[0]

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """分批编码，每批一次 API 调用。"""
        if not texts:
            return []
        results: list[list[float]] = []
        for i in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[i : i + self.BATCH_SIZE]
            vecs = await self._encode_single_batch(batch)
            results.extend(vecs)
        return results

    async def _encode_single_batch(self, texts: list[str]) -> list[list[float]]:
        """单批 API 调用，指数退避重试。"""
        for attempt in range(self.MAX_RETRIES):
            try:
                if self._has_batch:
                    return await self._model.batch_encode(texts)
                return [await self._model.encode(t) for t in texts]
            except Exception as exc:
                if _is_transient(exc) and attempt < self.MAX_RETRIES - 1:
                    delay = min(self.BACKOFF_BASE**attempt, 10)
                    delay += self._rng.random() * 0.5
                    logger.warning(
                        "Batch encode failed (attempt %d/%d): %s",
                        attempt + 1,
                        self.MAX_RETRIES,
                        exc,
                    )
                    await _SLEEP(delay)
                    continue
                raise
        msg = "unreachable"
        raise AssertionError(msg)
