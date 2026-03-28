"""Tests for the memory bank backend and integration."""

from unittest.mock import MagicMock

import pytest

from app.memory.schemas import MemoryEvent
from app.memory.stores.memory_bank_store import (
    DAILY_SUMMARY_THRESHOLD,
    OVERALL_SUMMARY_THRESHOLD,
    MemoryBankStore,
)

from app.memory.memory import MemoryModule
from app.memory.types import MemoryMode
from tests.conftest import SKIP_IF_NO_LLM


@pytest.fixture
def backend(tmp_path):
    """Provide a MemoryBankStore instance backed by a temporary directory."""
    return MemoryBankStore(str(tmp_path))


@pytest.fixture
def mock_chat_model():
    """Provide a mocked ChatModel that returns a fixed summary string."""
    chat = MagicMock()
    chat.generate.return_value = "测试摘要"
    return chat


class TestSearchWithForgetting:
    """Tests for search behavior with forgetting mechanism."""

    def test_search_no_embedding_returns_keyword(self, backend):
        """Verify that search falls back to keyword matching without embeddings."""
        backend.write(MemoryEvent(content="今天天气很好"))
        results = backend.search("天气")
        assert len(results) > 0
        assert "天气" in results[0].event["content"]

    def test_search_empty_events(self, backend):
        """Verify that searching with no events returns an empty list."""
        assert backend.search("测试") == []

    def test_search_returns_top_k(self, backend):
        """Verify that search results are limited to top-k results."""
        for i in range(10):
            backend.write(MemoryEvent(content=f"事件{i}关于天气"))
        results = backend.search("天气")
        assert len(results) <= 10


class TestRecallStrengthening:
    """Tests for recall-based memory strengthening."""

    def test_search_increases_memory_strength(self, backend):
        """Verify that searching an event increases its memory strength."""
        backend.write(MemoryEvent(content="重要的会议"))
        backend.search("会议")
        events = backend.events_store.read()
        assert events[0]["memory_strength"] == 2

    def test_search_updates_only_matched_events(self, backend):
        """Verify that only matched events have their memory strength updated."""
        backend.write(MemoryEvent(content="关于天气的事件"))
        backend.write(MemoryEvent(content="关于会议的事件"))
        backend.search("天气")
        events = backend.events_store.read()
        weather = [e for e in events if "天气" in e["content"]][0]
        meeting = [e for e in events if "会议" in e["content"]][0]
        assert weather["memory_strength"] == 2
        assert meeting["memory_strength"] == 1


class TestHierarchicalSummarization:
    """Tests for hierarchical daily and overall summarization."""

    def test_summarize_trigger_threshold(self, tmp_path, mock_chat_model):
        """Verify that daily summary is triggered when event count reaches the threshold."""
        backend = MemoryBankStore(tmp_path, chat_model=mock_chat_model)
        for i in range(DAILY_SUMMARY_THRESHOLD):
            backend.write(MemoryEvent(content=f"事件{i}"))
        summaries = backend.summaries_store.read()
        today = backend.events_store.read()[0]["date_group"]
        assert today in summaries["daily_summaries"]
        assert mock_chat_model.generate.called

    def test_no_summary_below_threshold(self, tmp_path, mock_chat_model):
        """Verify that no daily summary is created below the event threshold."""
        backend = MemoryBankStore(tmp_path, chat_model=mock_chat_model)
        for i in range(DAILY_SUMMARY_THRESHOLD - 1):
            backend.write(MemoryEvent(content=f"事件{i}"))
        summaries = backend.summaries_store.read()
        assert len(summaries["daily_summaries"]) == 0

    def test_overall_summary_trigger(self, tmp_path, mock_chat_model):
        """Verify that overall summary is triggered when daily summaries reach the threshold."""
        mock_chat_model.generate.return_value = "总体摘要"
        backend = MemoryBankStore(tmp_path, chat_model=mock_chat_model)
        summaries = backend.summaries_store.read()
        for i in range(OVERALL_SUMMARY_THRESHOLD):
            date_group = f"2026-03-{20 + i:02d}"
            summaries["daily_summaries"][date_group] = {
                "content": f"每日摘要{i}",
                "memory_strength": 1,
                "last_recall_date": date_group,
            }
        backend.summaries_store.write(summaries)
        backend._update_overall_summary(summaries["daily_summaries"], summaries)
        updated = backend.summaries_store.read()
        assert updated["overall_summary"] == "总体摘要"

    def test_summaries_included_in_search(self, tmp_path, mock_chat_model):
        """Verify that daily summaries are included in search results."""
        mock_chat_model.generate.return_value = "今天讨论了项目进度"
        backend = MemoryBankStore(tmp_path, chat_model=mock_chat_model)
        for i in range(DAILY_SUMMARY_THRESHOLD):
            backend.write(MemoryEvent(content=f"事件{i}关于项目"))
        results = backend.search("讨论了")
        sources = [r.source for r in results]
        assert "daily_summary" in sources


class TestUpdateEventSummary:
    """Tests for LLM-based event summary updates."""

    def test_llm_updates_event_content(self, tmp_path, mock_chat_model):
        """Verify that the LLM generates an updated event summary on aggregation."""
        mock_chat_model.generate.return_value = "用户修改了会议时间"
        backend = MemoryBankStore(tmp_path, chat_model=mock_chat_model)
        backend.write_interaction("提醒我明天上午开会", "好的", event_type="meeting")
        backend.write_interaction("明天下午也有会议", "已更新")
        events = backend.events_store.read()
        assert len(events) == 1
        assert events[0]["content"] == "用户修改了会议时间"

    def test_no_llm_preserves_original(self, backend):
        """Verify that the original content is preserved when no LLM is available."""
        backend.write_interaction("提醒我明天上午开会", "好的")
        backend.write_interaction("明天下午也有会议", "已更新")
        events = backend.events_store.read()
        assert events[0]["content"] == "提醒我明天上午开会"


@SKIP_IF_NO_LLM
class TestMemoryModuleIntegration:
    """Tests for full MemoryModule integration with the memory bank."""

    def test_write_interaction_flow(self, tmp_path):
        """Verify the end-to-end write interaction and search flow."""
        memory = MemoryModule(str(tmp_path))
        memory.write_interaction("测试查询", "测试回复")
        results = memory.search("测试", mode=MemoryMode.MEMORY_BANK)
        assert len(results) > 0
        assert len(results[0].interactions) >= 1
