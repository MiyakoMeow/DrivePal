"""关键词匹配检索 store."""

from app.memory.stores.base import BaseMemoryStore

_STORE_NAME = "keyword"


class KeywordMemoryStore(BaseMemoryStore):
    """关键词匹配检索 store."""

    @property
    def store_name(self) -> str:
        """返回存储名称."""
        return _STORE_NAME
