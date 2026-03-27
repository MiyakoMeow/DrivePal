"""Tests for LLMOnlyMemoryStore."""

from unittest.mock import MagicMock

import pytest

from app.memory.stores.llm_store import LLMOnlyMemoryStore


@pytest.fixture
def mock_chat_model():
    chat = MagicMock()
    chat.generate.return_value = '{"relevant": true, "reasoning": "测试"}'
    return chat


@pytest.fixture
def store(tmp_path, mock_chat_model):
    return LLMOnlyMemoryStore(str(tmp_path), chat_model=mock_chat_model)


@pytest.fixture
def store_without_llm(tmp_path):
    return LLMOnlyMemoryStore(str(tmp_path), chat_model=None)


class TestLLMOnlyMemoryStore:
    def test_write_returns_event_id(self, store):
        event_id = store.write({"content": "测试事件"})
        assert isinstance(event_id, str)

    def test_search_with_llm_returns_relevant(self, store):
        store.write({"content": "明天有会议"})
        results = store.search("有什么安排")
        assert len(results) == 1

    def test_search_without_llm_returns_empty(self, store_without_llm):
        store_without_llm.write({"content": "测试事件"})
        results = store_without_llm.search("测试")
        assert results == []

    def test_search_no_events_returns_empty(self, store):
        results = store.search("测试")
        assert results == []
