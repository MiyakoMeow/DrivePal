"""ChatModel 薄封装：4 消息序列 + 重试时自动截断 prompt 上下文。"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from app.models.chat import AllProviderFailedError

if TYPE_CHECKING:
    import random

logger = logging.getLogger(__name__)

LLM_MAX_RETRIES = 3
LLM_NONTRANSIENT_MAX_RETRIES = 1
LLM_TRIM_START = 1800
LLM_TRIM_STEP = 200
LLM_TRIM_MIN = 500

_sleep = asyncio.sleep

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

_ANCHOR_USER = "Hello! Please help me summarize the content of the conversation."
_ANCHOR_ASSISTANT = "Sure, I will do my best to assist you."
_DEFAULT_SYSTEM = (
    "You are an in-car AI assistant with expertise in remembering "
    "vehicle preferences, driving habits, and in-car conversation context."
)


class LlmClient:
    """ChatModel 的薄封装，4 消息序列 + 上下文截断重试。"""

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
        """调用 ChatModel.generate()，使用 4 消息序列。

        消息序列：system → user（锚定）→ assistant（应承）→ user（实际 prompt）。
        重试时截断 messages[-1]["content"]。
        """
        messages = [
            {
                "role": "system",
                "content": system_prompt
                if system_prompt is not None
                else _DEFAULT_SYSTEM,
            },
            {"role": "user", "content": _ANCHOR_USER},
            {"role": "assistant", "content": _ANCHOR_ASSISTANT},
            {"role": "user", "content": prompt},
        ]
        for attempt in range(LLM_MAX_RETRIES):
            try:
                resp = await self._chat_model.generate(messages=messages)
                return resp.strip() if resp else ""
            except AllProviderFailedError as exc:
                err = str(exc).lower()
                if (
                    any(p in err for p in _CONTEXT_EXCEEDED_PATTERNS)
                    and attempt < LLM_MAX_RETRIES - 1
                ):
                    cut = max(LLM_TRIM_START - LLM_TRIM_STEP * attempt, LLM_TRIM_MIN)
                    messages[-1]["content"] = messages[-1]["content"][-cut:]
                    continue
                if (
                    any(p in err for p in _TRANSIENT_PATTERNS)
                    and attempt < LLM_MAX_RETRIES - 1
                ):
                    delay = min(2**attempt, 10)
                    if self._rng is not None:
                        delay += self._rng.random() * 0.5
                    await _sleep(delay)
                    continue
                if attempt < LLM_NONTRANSIENT_MAX_RETRIES:
                    continue
                logger.warning(
                    "LlmClient retries exhausted after %d attempts: %s",
                    attempt + 1,
                    exc,
                )
                return None
        return None
