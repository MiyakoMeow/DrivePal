"""ChatModel 薄封装：4 消息序列 + 重试时自动截断 prompt 上下文。"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from app.memory.exceptions import LLMCallFailed, SummarizationEmpty
from app.models.chat import AllProviderFailedError

if TYPE_CHECKING:
    import random

    from .config import MemoryBankConfig

logger = logging.getLogger(__name__)

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


class LlmClient:
    """ChatModel 的薄封装，4 消息序列 + 上下文截断重试。"""

    def __init__(
        self,
        chat_model: Any,
        config: MemoryBankConfig,
        *,
        rng: random.Random | None = None,
    ) -> None:
        self._chat_model = chat_model
        self._config = config
        self._rng = rng

    async def call(self, prompt: str, *, system_prompt: str, **kwargs: object) -> str:
        """调用 ChatModel.generate()，使用 4 消息序列。

        消息序列：system → user（锚定）→ assistant（应承）→ user（实际 prompt）。

        成功返回非空 str。
        抛出 LLMCallFailed（API 失败，重试耗尽）。
        抛出 SummarizationEmpty（LLM 返回空内容——非错误，哨兵异常）。

        Args:
            prompt: 实际提示词。
            system_prompt: system 消息内容（调用方从 config 获取）。
            **kwargs: 透传给 ChatModel.generate() 的额外参数（如 temperature）。

        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": self._config.llm_anchor_user},
            {"role": "assistant", "content": self._config.llm_anchor_assistant},
            {"role": "user", "content": prompt},
        ]
        for attempt in range(self._config.llm_max_retries):
            try:
                resp = await self._chat_model.generate(
                    messages=messages,
                    **{k: v for k, v in kwargs.items() if v is not None},
                )
                if not resp or not resp.strip():
                    raise SummarizationEmpty("LLM returned empty content")
                return resp.strip()
            except SummarizationEmpty:
                raise
            except AllProviderFailedError as exc:
                err = str(exc).lower()
                if (
                    any(p in err for p in _CONTEXT_EXCEEDED_PATTERNS)
                    and attempt < self._config.llm_max_retries - 1
                ):
                    cut = max(
                        self._config.llm_trim_start
                        - self._config.llm_trim_step * attempt,
                        self._config.llm_trim_min,
                    )
                    messages[-1]["content"] = messages[-1]["content"][-cut:]
                    continue
                if (
                    any(p in err for p in _TRANSIENT_PATTERNS)
                    and attempt < self._config.llm_max_retries - 1
                ):
                    delay = min(2**attempt, 10)
                    if self._rng is not None:
                        delay += self._rng.random() * 0.5
                    await _sleep(delay)
                    continue
                # 非瞬态错误：再多一次尝试
                if attempt < self._config.llm_max_retries - 2:
                    continue
                raise LLMCallFailed(
                    f"LLM call failed after {attempt + 1} attempts: {exc}"
                ) from exc
        raise LLMCallFailed(
            f"LLM call failed after {self._config.llm_max_retries} attempts"
        )
