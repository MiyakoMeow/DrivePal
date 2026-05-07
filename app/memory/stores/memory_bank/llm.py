"""ChatModel 薄封装：重试时自动截断 prompt 上下文。"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from app.models.chat import AllProviderFailedError

if TYPE_CHECKING:
    import random

logger = logging.getLogger(__name__)

LLM_MAX_RETRIES = 3
LLM_TRIM_START = 1800
LLM_TRIM_STEP = 200
LLM_TRIM_MIN = 500

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
_CONTEXT_EXCEEDED_PATTERNS = (
    "maximum context",
    "context length",
    "too long",
    "reduce the length",
    "input length",
)


class LlmClient:
    """ChatModel 的薄封装，提供上下文截断重试。"""

    def __init__(self, chat_model: Any, *, rng: random.Random | None = None) -> None:
        """初始化 LlmClient。

        Args:
            chat_model: 聊天模型实例（须有 generate 方法）。
            rng: 可选 RNG 实例（用于重试退避 jitter）。

        """
        self._chat_model = chat_model
        self._rng = rng

    async def call(
        self, prompt: str, *, system_prompt: str | None = None
    ) -> str | None:
        """调用 ChatModel.generate()，重试时自动截断 prompt 头部（保留末尾最新内容）。

        AllProviderFailedError 外的不明异常会传播到上层，不在此处静默吞掉。
        """
        for attempt in range(LLM_MAX_RETRIES):
            try:
                resp = await self._chat_model.generate(
                    prompt=prompt,
                    system_prompt=system_prompt or None,
                )
                return resp.strip() if resp else ""
            except AllProviderFailedError as exc:
                err = str(exc).lower()
                # 上下文超长 → 截断后重试
                if (
                    any(p in err for p in _CONTEXT_EXCEEDED_PATTERNS)
                    and attempt < LLM_MAX_RETRIES - 1
                ):
                    prompt = prompt[
                        -max(LLM_TRIM_START - LLM_TRIM_STEP * attempt, LLM_TRIM_MIN) :
                    ]
                    continue
                # 瞬态错误 → 指数退避后重试
                if (
                    any(p in err for p in _TRANSIENT_PATTERNS)
                    and attempt < LLM_MAX_RETRIES - 1
                ):
                    delay = min(2**attempt, 10)
                    if self._rng:
                        delay += self._rng.random() * 0.5
                    await asyncio.sleep(delay)
                    continue
                # 其他错误（鉴权/模型不存在等）：立即重试一次
                if attempt < LLM_MAX_RETRIES - 1:
                    continue
                logger.warning(
                    "LlmClient retries exhausted after %d attempts: %s",
                    LLM_MAX_RETRIES,
                    exc,
                )
                return None
        return None
