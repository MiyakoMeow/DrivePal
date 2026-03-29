from adapters.memory_adapters.common import StoreClient, history_to_interaction_records
from adapters.model_config import get_store_embedding_model
from app.memory.stores.embedding_store import EmbeddingMemoryStore


class EmbeddingsAdapter:
    TAG = "embeddings"

    def __init__(self, data_dir: str):
        self.data_dir = data_dir

    def add(self, history_text: str) -> EmbeddingMemoryStore:
        embedding_model = get_store_embedding_model()
        store = EmbeddingMemoryStore(
            data_dir=self.data_dir, embedding_model=embedding_model
        )
        for record in history_to_interaction_records(history_text):
            store.write(record)
        return store

    def get_search_client(self, store) -> StoreClient:
        return StoreClient(store)

    def init_state(self):
        return None

    def close_state(self, state):
        pass
