"""MemoryStore 抽象接口定义."""

from abc import ABC, abstractmethod

from app.memory.schemas import FeedbackData, MemoryEvent, SearchResult


class MemoryStore(ABC):
    """记忆存储抽象接口."""

    requires_embedding: bool = False
    requires_chat: bool = False
    supports_interaction: bool = False

    @property
    @abstractmethod
    def store_name(self) -> str:
        """存储名称，用于注册和路由."""
        pass

    @abstractmethod
    def write(self, event: MemoryEvent) -> str:
        """写入事件，返回 event_id."""
        pass

    @abstractmethod
    def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        """检索记忆，返回匹配的结果列表."""
        pass

    def get_history(self, limit: int = 10) -> list[MemoryEvent]:
        """获取历史记录，按时间倒序返回最近 limit 条."""
        raise NotImplementedError

    def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        """更新反馈，同时更新策略权重."""
        raise NotImplementedError

    def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str:
        """写入交互记录，返回 event_id."""
        raise NotImplementedError
