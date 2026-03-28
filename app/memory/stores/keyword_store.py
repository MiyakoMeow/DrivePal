"""关键词匹配检索 store."""

from app.memory.stores.base import BaseMemoryStore

_STORE_NAME = "keyword"


class KeywordMemoryStore(BaseMemoryStore):
    @property
    def store_name(self) -> str:
        return _STORE_NAME
