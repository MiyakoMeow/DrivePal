"""Tests for EmbeddingMemoryStore."""

from unittest.mock import MagicMock

import pytest
from app.memory.schemas import MemoryEvent, SearchResult
from app.memory.stores.embedding_store import EmbeddingMemoryStore


@pytest.fixture
def mock_embedding_model():
    model = MagicMock()
    model.encode.return_value = [0.1] * 128
    model.batch_encode.return_value = [[0.1] * 128] * 10
    return model


@pytest.fixture
def store(tmp_path, mock_embedding_model):
    return EmbeddingMemoryStore(str(tmp_path), embedding_model=mock_embedding_model)


@pytest.fixture
def store_without_embedding(tmp_path):
    return EmbeddingMemoryStore(str(tmp_path), embedding_model=None)


class TestEmbeddingMemoryStore:
    def test_write_returns_event_id(self, store):
        event_id = store.write(MemoryEvent(content="测试事件"))
        assert isinstance(event_id, str)

    def test_search_with_embedding(self, store):
        store.write(MemoryEvent(content="明天有会议"))
        results = store.search("有什么安排")
        assert len(results) == 1
        assert isinstance(results[0], SearchResult)

    def test_search_without_embedding_falls_back_to_keyword(
        self, store_without_embedding
    ):
        store_without_embedding.write(MemoryEvent(content="测试事件"))
        results = store_without_embedding.search("测试")
        assert len(results) == 1

    def test_search_no_events_returns_empty(self, store):
        results = store.search("测试")
        assert results == []
