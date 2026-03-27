"""Tests for MemoryBankStore."""

from unittest.mock import MagicMock

import pytest

from app.memory.stores.memory_bank_store import (
    DAILY_SUMMARY_THRESHOLD,
    MemoryBankStore,
)


@pytest.fixture
def mock_chat_model():
    chat = MagicMock()
    chat.generate.return_value = "测试摘要"
    return chat


@pytest.fixture
def store(tmp_path):
    return MemoryBankStore(str(tmp_path))


@pytest.fixture
def store_with_llm(tmp_path, mock_chat_model):
    return MemoryBankStore(str(tmp_path), chat_model=mock_chat_model)


class TestSearchWithForgetting:
    def test_search_no_embedding_returns_keyword(self, store):
        store.write({"content": "今天天气很好"})
        results = store.search("天气")
        assert len(results) > 0
        assert "天气" in results[0]["content"]

    def test_search_empty_events(self, store):
        assert store.search("测试") == []

    def test_search_returns_top_k(self, store):
        for i in range(10):
            store.write({"content": f"事件{i}关于天气"})
        results = store.search("天气")
        assert len(results) <= 3


class TestRecallStrengthening:
    def test_search_increases_memory_strength(self, store):
        store.write({"content": "重要的会议"})
        store.search("会议")
        events = store.events_store.read()
        assert events[0]["memory_strength"] == 2

    def test_search_updates_only_matched_events(self, store):
        store.write({"content": "关于天气的事件"})
        store.write({"content": "关于会议的事件"})
        store.search("天气")
        events = store.events_store.read()
        weather = [e for e in events if "天气" in e["content"]][0]
        meeting = [e for e in events if "会议" in e["content"]][0]
        assert weather["memory_strength"] == 2
        assert meeting["memory_strength"] == 1


class TestHierarchicalSummarization:
    def test_summarize_trigger_threshold(self, tmp_path, mock_chat_model):
        backend = MemoryBankStore(str(tmp_path), chat_model=mock_chat_model)
        for i in range(DAILY_SUMMARY_THRESHOLD):
            backend.write({"content": f"事件{i}"})
        summaries = backend.summaries_store.read()
        today = backend.events_store.read()[0]["date_group"]
        assert today in summaries["daily_summaries"]
        assert mock_chat_model.generate.called

    def test_no_summary_below_threshold(self, tmp_path, mock_chat_model):
        backend = MemoryBankStore(str(tmp_path), chat_model=mock_chat_model)
        for i in range(DAILY_SUMMARY_THRESHOLD - 1):
            backend.write({"content": f"事件{i}"})
        summaries = backend.summaries_store.read()
        assert len(summaries["daily_summaries"]) == 0


class TestWriteInteraction:
    def test_write_interaction_creates_record(self, store):
        interaction_id = store.write_interaction("提醒我开会", "好的")
        assert isinstance(interaction_id, str)
        interactions = store.interactions_store.read()
        assert interactions[0]["id"] == interaction_id

    def test_write_interaction_aggregates_similar(self, store):
        store.write_interaction("提醒我明天上午开会", "好的")
        store.write_interaction("明天下午也有会议", "已更新")
        events = store.events_store.read()
        assert len(events) == 1
        assert len(events[0]["interaction_ids"]) == 2
