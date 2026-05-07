"""弹性 embedding 封装，对标 LlmClient。"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

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


class EmbeddingClient:
    """EmbeddingModel 的弹性封装，提供单条编码重试和分批编码。"""

    MAX_RETRIES = 5
    BACKOFF_BASE = 2
    BATCH_SIZE = 100

    def __init__(
        self,
        embedding_model: Any,
        *,
        rng: random.Random | None = None,
    ) -> None:
        """初始化 EmbeddingClient。

        Args:
            embedding_model: 嵌入模型实例。
            rng: 可选 RNG 实例（用于退避 jitter）。

        """
        self._model = embedding_model
        self._rng = rng if rng is not None else random.Random()

    async def encode(self, text: str) -> list[float]:
        """编码单条文本，瞬态错误时指数退避重试。"""
        for attempt in range(self.MAX_RETRIES):
            try:
                return await self._model.encode(text)
            except Exception as exc:
                err = str(exc).lower()
                if (
                    any(p in err for p in _TRANSIENT_PATTERNS)
                    and attempt < self.MAX_RETRIES - 1
                ):
                    delay = min(self.BACKOFF_BASE**attempt, 10)
                    delay += self._rng.random() * 0.5
                    await _SLEEP(delay)
                    continue
                raise
        return await self._model.encode(text)

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """分批编码，每条走 encode() 以使用统一重试策略。"""
        if not texts:
            return []
        results: list[list[float]] = []
        for i in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[i : i + self.BATCH_SIZE]
            for text in batch:
                vec = await self.encode(text)
                results.append(vec)
        return results
