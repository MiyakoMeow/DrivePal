"""MemoryStore 结构化接口定义（Protocol，多用户版）。"""

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.memory.schemas import (
        FeedbackData,
        InteractionResult,
        MemoryEvent,
        SearchResult,
    )


class MemoryStore(Protocol):
    """记忆存储接口，多用户版。"""

    store_name: str
    requires_embedding: bool
    requires_chat: bool

    async def write(self, user_id: str, event: MemoryEvent) -> str: ...

    async def write_interaction(
        self,
        user_id: str,
        query: str,
        response: str,
        event_type: str = "reminder",
        *,
        user_name: str = "User",
        ai_name: str = "AI",
    ) -> InteractionResult: ...

    async def search(
        self, user_id: str, query: str, top_k: int = 5
    ) -> list[SearchResult]: ...

    async def get_history(self, user_id: str, limit: int = 10) -> list[MemoryEvent]: ...

    async def get_event_type(self, user_id: str, event_id: str) -> str | None: ...

    async def update_feedback(
        self, user_id: str, event_id: str, feedback: FeedbackData
    ) -> None: ...
