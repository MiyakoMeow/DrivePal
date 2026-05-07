"""ChatModel 薄封装：重试时自动截断 prompt 上下文。"""

import logging
import random
from typing import TYPE_CHECKING

from app.models.chat import AllProviderFailedError

if TYPE_CHECKING:
    from app.models.chat import ChatModel

logger = logging.getLogger(__name__)

LLM_MAX_RETRIES = 3
LLM_TRIM_START = 1800
LLM_TRIM_STEP = 200
LLM_TRIM_MIN = 500


class LlmClient:
    """ChatModel 的薄封装，提供上下文截断重试。"""

    def __init__(self, chat_model: ChatModel, *, rng: random.Random | None = None) -> None:
        """初始化 LlmClient。

        Args:
            chat_model: 聊天模型实例。
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
                is_ctx = any(
                    p in err
                    for p in (
                        "maximum context",
                        "context length",
                        "too long",
                        "reduce the length",
                        "input length",
                    )
                )
                if is_ctx and attempt < LLM_MAX_RETRIES - 1:
                    prompt = prompt[
                        -max(LLM_TRIM_START - LLM_TRIM_STEP * attempt, LLM_TRIM_MIN) :
                    ]
                    continue
                if attempt < LLM_MAX_RETRIES - 1:
                    continue
                logger.warning("LlmClient 重试 %d 次后仍失败", LLM_MAX_RETRIES)
                return None
        return None
