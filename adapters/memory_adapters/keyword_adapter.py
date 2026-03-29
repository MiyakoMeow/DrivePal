"""Keyword-based memory adapter."""

from adapters.memory_adapters.common import StoreClient, history_to_interaction_records
from app.memory.stores.keyword_store import KeywordMemoryStore


class KeywordAdapter:
    """Adapter using keyword-based search."""

    TAG = "keyword"

    def __init__(self, data_dir: str):
        """Initialize with data directory."""
        self.data_dir = data_dir

    def add(self, history_text: str) -> KeywordMemoryStore:
        """Add history text to the keyword store."""
        store = KeywordMemoryStore(data_dir=self.data_dir)
        for record in history_to_interaction_records(history_text):
            store.write(record)
        return store

    def get_search_client(self, store) -> StoreClient:
        """Get a search client for the store."""
        return StoreClient(store)

    def init_state(self):
        """Initialize state (no-op for this adapter)."""
        return None

    def close_state(self, state):
        """Close state (no-op for this adapter)."""
        pass
