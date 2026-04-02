"""统一聊天模型协议."""

from __future__ import annotations

from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class ChatModelProtocol(Protocol):
    """聊天模型统一接口."""

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        **kwargs: object,
    ) -> str:
        """生成回复."""
        ...

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        **kwargs: object,
    ) -> AsyncIterator[str]:
        """流式生成回复."""
        ...

    async def batch_generate(
        self,
        prompts: list[str],
        system_prompt: str | None = None,
    ) -> list[str]:
        """批量生成回复."""
        ...

    def is_available(self) -> bool:
        """检查模型是否可用."""
        ...
