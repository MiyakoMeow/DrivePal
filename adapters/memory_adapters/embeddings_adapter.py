"""Embeddings-based memory adapter."""

from adapters.memory_adapters.common import StoreClient, history_to_interaction_records
from adapters.model_config import get_store_embedding_model
from app.memory.stores.embedding_store import EmbeddingMemoryStore


class EmbeddingsAdapter:
    """Adapter using embeddings for semantic search."""

    TAG = "embeddings"

    def __init__(self, data_dir: str):
        """Initialize with data directory."""
        self.data_dir = data_dir

    def add(self, history_text: str) -> EmbeddingMemoryStore:
        """Add history text to the embedding store."""
        embedding_model = get_store_embedding_model()
        store = EmbeddingMemoryStore(
            data_dir=self.data_dir, embedding_model=embedding_model
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
