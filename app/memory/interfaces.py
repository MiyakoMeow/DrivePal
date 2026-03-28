"""MemoryStore 抽象接口定义."""

from abc import ABC, abstractmethod


class MemoryStore(ABC):
    """记忆存储抽象接口."""

    @property
    @abstractmethod
    def store_name(self) -> str:
        """存储名称，用于注册和路由."""
        pass

    @abstractmethod
    def write(self, event: dict) -> str:
        """写入事件，返回 event_id."""
        pass

    @abstractmethod
    def search(self, query: str) -> list[dict]:
        """检索记忆，返回匹配的事件列表."""
        pass

    @abstractmethod
    def get_history(self, limit: int = 10) -> list[dict]:
        """获取历史记录，按时间倒序返回最近 limit 条."""
        pass

    @abstractmethod
    def update_feedback(self, event_id: str, feedback: dict) -> None:
        """更新反馈，同时更新策略权重."""
        pass

    @abstractmethod
    def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str:
        """写入交互记录，返回 event_id."""
        pass
