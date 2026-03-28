"""MemoryStore 基类，提供共享的 events_store 和通用逻辑."""

from abc import ABC
from datetime import datetime
from app.memory.interfaces import MemoryStore
from app.storage.json_store import JSONStore


class BaseMemoryStore(MemoryStore, ABC):
    """MemoryStore 基类."""

    requires_embedding: bool = False
    requires_chat: bool = False
    supports_interaction: bool = False

    def __init__(
        self,
        data_dir: str,
        embedding_model=None,
        chat_model=None,
    ) -> None:
        """初始化 BaseMemoryStore 实例.

        Args:
            data_dir: 数据存储目录路径.
            embedding_model: 向量嵌入模型 (可选).
            chat_model: 聊天模型 (可选).

        """
        self.data_dir = data_dir
        self.events_store = JSONStore(data_dir, "events.json", list)
        self.strategies_store = JSONStore(data_dir, "strategies.json", dict)

    def get_history(self, limit: int = 10) -> list[dict]:
        """获取历史记录，按时间倒序返回最近 limit 条.

        Args:
            limit: 返回记录数量上限.

        Returns:
            事件列表.

        """
        events = self.events_store.read()
        if limit <= 0:
            return []
        return events[-limit:]

    def update_feedback(self, event_id: str, feedback: dict) -> None:
        """更新反馈，同时更新策略权重.

        Args:
            event_id: 事件ID.
            feedback: 反馈数据，包含 action 和 type 等字段.

        """
        feedback_store = JSONStore(self.data_dir, "feedback.json", list)
        feedback["event_id"] = event_id
        feedback["timestamp"] = datetime.now().isoformat()
        feedback_store.append(feedback)
        self._update_strategy(event_id, feedback)

    def _update_strategy(self, event_id: str, feedback: dict) -> None:
        strategies = self.strategies_store.read()
        action = feedback.get("action")
        event_type = feedback.get("type", "default")

        if "reminder_weights" not in strategies:
            strategies["reminder_weights"] = {}

        if action == "accept":
            strategies["reminder_weights"][event_type] = min(
                strategies["reminder_weights"].get(event_type, 0.5) + 0.1, 1.0
            )
        elif action == "ignore":
            strategies["reminder_weights"][event_type] = max(
                strategies["reminder_weights"].get(event_type, 0.5) - 0.1, 0.1
            )

        self.strategies_store.write(strategies)

    def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str:
        """将交互记录作为普通事件写入.

        Args:
            query: 用户查询.
            response: 系统响应.
            event_type: 事件类型.

        Returns:
            事件 ID.

        """
        return self.write({"content": response, "type": event_type})
