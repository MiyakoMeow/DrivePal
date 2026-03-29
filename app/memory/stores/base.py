"""MemoryStore 基类，提供共享的 events_store 和通用逻辑."""

import uuid
from abc import ABC
from datetime import datetime

from app.memory.interfaces import MemoryStore
from app.memory.schemas import FeedbackData, MemoryEvent, SearchResult
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
        """初始化基础记忆存储."""
        self.data_dir = data_dir
        self.events_store = JSONStore(data_dir, "events.json", list)
        self.strategies_store = JSONStore(data_dir, "strategies.json", dict)

    def _generate_id(self) -> str:
        return f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

    def write(self, event: MemoryEvent) -> str:
        """写入记忆事件，自动生成 ID 和时间戳."""
        event = event.model_copy(deep=True)
        event.id = self._generate_id()
        event.created_at = datetime.now().isoformat()
        self.events_store.append(event.model_dump())
        return event.id

    def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        """基于关键词匹配检索记忆事件."""
        events = self.events_store.read()
        matched = self._keyword_search(query, events)
        return [SearchResult(event=e) for e in matched[:top_k]]

    def _keyword_search(self, query: str, events: list[dict]) -> list[dict]:
        query_lower = query.lower()
        return [
            e
            for e in events
            if query_lower in e.get("content", "").lower()
            or query_lower in e.get("description", "").lower()
        ]

    def get_history(self, limit: int = 10) -> list[MemoryEvent]:
        """获取最近的历史记忆事件."""
        events = self.events_store.read()
        if limit <= 0:
            return []
        return [MemoryEvent(**e) for e in events[-limit:]]

    def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        """更新事件反馈并调整策略权重."""
        feedback.event_id = event_id
        feedback.timestamp = datetime.now().isoformat()
        feedback_store = JSONStore(self.data_dir, "feedback.json", list)
        feedback_store.append(feedback.model_dump())
        self._update_strategy(event_id, feedback.model_dump())

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
        """写入交互记录并创建对应的记忆事件."""
        event = MemoryEvent(
            content=query,
            type=event_type,
            description=response,
        )
        return self.write(event)
