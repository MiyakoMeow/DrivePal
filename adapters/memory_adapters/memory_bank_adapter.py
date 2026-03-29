"""Memory bank adapter combining embeddings and LLM."""

from adapters.memory_adapters.common import StoreClient, history_to_interaction_records
from adapters.model_config import get_store_chat_model, get_store_embedding_model
from app.memory.stores.memory_bank_store import MemoryBankStore


class MemoryBankAdapter:
    """Adapter combining embeddings and LLM for memory search."""

    TAG = "memory_bank"

    def __init__(self, data_dir: str):
        """Initialize with data directory."""
        self.data_dir = data_dir

    def add(self, history_text: str) -> MemoryBankStore:
        """Add history text to the memory bank store."""
        chat_model = get_store_chat_model()
        embedding_model = get_store_embedding_model()
        store = MemoryBankStore(
            data_dir=self.data_dir,
            chat_model=chat_model,
            embedding_model=embedding_model,
        )
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
