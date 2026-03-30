"""EmbeddingMemoryStore 测试."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from app.memory.schemas import MemoryEvent, SearchResult
from app.memory.stores.embedding_store import EmbeddingMemoryStore


@pytest.fixture
def mock_embedding_model() -> MagicMock:
    """Create a mock embedding model."""
    model = MagicMock()
    model.encode.return_value = [0.1] * 128
    model.batch_encode.return_value = [[0.1] * 128] * 10
    return model


@pytest.fixture
def store(tmp_path: Path, mock_embedding_model: MagicMock) -> EmbeddingMemoryStore:
    """Create an EmbeddingMemoryStore with mock embedding model."""
    return EmbeddingMemoryStore(tmp_path, embedding_model=mock_embedding_model)


@pytest.fixture
def store_without_embedding(tmp_path: Path) -> EmbeddingMemoryStore:
    """Create an EmbeddingMemoryStore without embedding model."""
    return EmbeddingMemoryStore(tmp_path, embedding_model=None)


class TestEmbeddingMemoryStore:
    """Tests for EmbeddingMemoryStore class."""

    def test_write_returns_event_id(self, store: EmbeddingMemoryStore) -> None:
        """Test that write returns a string event ID."""
        event_id = store.write(MemoryEvent(content="测试事件"))
        assert isinstance(event_id, str)

    def test_search_with_embedding(self, store: EmbeddingMemoryStore) -> None:
        """Test search uses embeddings when available."""
        store.write(MemoryEvent(content="明天有会议"))
        results = store.search("有什么安排")
        assert len(results) == 1
        assert isinstance(results[0], SearchResult)

    def test_search_without_embedding_falls_back_to_keyword(
        self, store_without_embedding: EmbeddingMemoryStore
    ) -> None:
        """Test search falls back to keyword when no embedding model."""
        store_without_embedding.write(MemoryEvent(content="测试事件"))
        results = store_without_embedding.search("测试")
        assert len(results) == 1

    def test_search_no_events_returns_empty(self, store: EmbeddingMemoryStore) -> None:
        """Test search returns empty list when no events exist."""
        results = store.search("测试")
        assert results == []
