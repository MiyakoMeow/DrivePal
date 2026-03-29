"""MemoryStore 结构化接口定义（Protocol）."""

from typing import Protocol

from app.memory.schemas import FeedbackData, MemoryEvent, SearchResult


class MemoryStore(Protocol):
    """记忆存储接口，通过结构化子类型隐式满足."""

    store_name: str
    requires_embedding: bool
    requires_chat: bool
    supports_interaction: bool

    def write(self, event: MemoryEvent) -> str: ...
    def search(self, query: str, top_k: int = 10) -> list[SearchResult]: ...
    def get_history(self, limit: int = 10) -> list[MemoryEvent]: ...
    def update_feedback(self, event_id: str, feedback: FeedbackData) -> None: ...
    def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str: ...
