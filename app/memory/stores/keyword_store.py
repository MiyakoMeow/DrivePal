"""关键词匹配检索 store."""

import uuid
from datetime import datetime
from app.memory.stores.base import BaseMemoryStore

_STORE_NAME = "keyword"


class KeywordMemoryStore(BaseMemoryStore):
    """关键词匹配检索 store."""

    @property
    def store_name(self) -> str:
        """返回 store 名称."""
        return _STORE_NAME

    def write(self, event: dict) -> str:
        """写入事件到 store.

        Args:
            event: 事件数据字典

        Returns:
            事件 ID
        """
        event = dict(event)
        event_id = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
        event["id"] = event_id
        event["created_at"] = datetime.now().isoformat()
        self.events_store.append(event)
        return event_id

    def search(self, query: str) -> list[dict]:
        """搜索匹配关键词的事件.

        Args:
            query: 搜索关键词

        Returns:
            匹配的事件列表
        """
        query_lower = query.lower()
        events = self.events_store.read()
        return [
            event
            for event in events
            if query_lower in event.get("content", "").lower()
            or query_lower in event.get("description", "").lower()
        ]
