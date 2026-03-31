"""MemoryStore 结构化接口定义（Protocol）."""

from typing import Protocol

from app.memory.schemas import FeedbackData, MemoryEvent, SearchResult


class MemoryStore(Protocol):
    """记忆存储接口，通过结构化子类型隐式满足."""

    store_name: str
    requires_embedding: bool
    requires_chat: bool
    supports_interaction: bool

    async def write(self, event: MemoryEvent) -> str:
        """写入事件."""
        ...

    async def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        """搜索记忆."""
        ...

    async def get_history(self, limit: int = 10) -> list[MemoryEvent]:
        """获取历史事件."""
        ...

    async def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        """更新反馈."""
        ...

    async def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str:
        """写入交互记录."""
        ...
