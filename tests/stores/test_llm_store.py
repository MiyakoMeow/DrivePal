"""LLMOnlyMemoryStore 测试."""

from unittest.mock import MagicMock

import pytest
from app.memory.schemas import MemoryEvent, SearchResult
from app.memory.stores.llm_store import LLMOnlyMemoryStore


@pytest.fixture
def mock_chat_model():
    """Create a mock chat model."""
    chat = MagicMock()
    chat.generate.return_value = '{"relevant": true, "reasoning": "测试"}'
    return chat


@pytest.fixture
def store(tmp_path, mock_chat_model):
    """Create an LLMOnlyMemoryStore with mock chat model."""
    return LLMOnlyMemoryStore(str(tmp_path), chat_model=mock_chat_model)


@pytest.fixture
def store_without_llm(tmp_path):
    """Create an LLMOnlyMemoryStore without chat model."""
    return LLMOnlyMemoryStore(str(tmp_path), chat_model=None)


class TestLLMOnlyMemoryStore:
    """Tests for LLMOnlyMemoryStore class."""

    def test_write_returns_event_id(self, store):
        """Test that write returns a string event ID."""
        event_id = store.write(MemoryEvent(content="测试事件"))
        assert isinstance(event_id, str)

    def test_search_with_llm_returns_relevant(self, store):
        """Test that search uses LLM to determine relevance."""
        store.write(MemoryEvent(content="明天有会议"))
        results = store.search("有什么安排")
        assert len(results) == 1
        assert isinstance(results[0], SearchResult)

    def test_search_without_llm_returns_empty(self, store_without_llm):
        """Test that search returns empty when no LLM is available."""
        store_without_llm.write(MemoryEvent(content="测试事件"))
        results = store_without_llm.search("测试")
        assert results == []

    def test_search_no_events_returns_empty(self, store):
        """Test that search returns empty list when no events exist."""
        results = store.search("测试")
        assert results == []
