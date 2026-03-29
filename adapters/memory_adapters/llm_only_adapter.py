"""LLM-only memory adapter."""

from adapters.memory_adapters.common import StoreClient, history_to_interaction_records
from adapters.model_config import get_store_chat_model
from app.memory.stores.llm_store import LLMOnlyMemoryStore


class LLMOnlyAdapter:
    """Adapter using LLM for relevance determination."""

    TAG = "llm_only"

    def __init__(self, data_dir: str):
        """Initialize with data directory."""
        self.data_dir = data_dir

    def add(self, history_text: str) -> LLMOnlyMemoryStore:
        """Add history text to the LLM store."""
        chat_model = get_store_chat_model()
        store = LLMOnlyMemoryStore(data_dir=self.data_dir, chat_model=chat_model)
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
