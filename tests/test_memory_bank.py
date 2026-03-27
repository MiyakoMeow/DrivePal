import tempfile
from unittest.mock import MagicMock

import pytest

from app.memory.memory_bank import (
    DAILY_SUMMARY_THRESHOLD,
    MemoryBankBackend,
    forgetting_curve,
)


@pytest.fixture
def temp_data_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def backend(temp_data_dir):
    return MemoryBankBackend(temp_data_dir)


@pytest.fixture
def mock_chat_model():
    chat = MagicMock()
    chat.generate.return_value = "测试摘要"
    return chat


class TestForgettingCurve:
    def test_high_strength_recent_recall(self):
        result = forgetting_curve(0, 5)
        assert abs(result - 1.0) < 0.001

    def test_low_strength_old_recall(self):
        result = forgetting_curve(30, 1)
        assert result < 0.01

    def test_zero_days_always_one(self):
        result = forgetting_curve(0, 1)
        assert abs(result - 1.0) < 0.001

    def test_retention_decreases_with_time(self):
        r1 = forgetting_curve(1, 5)
        r2 = forgetting_curve(30, 5)
        assert r1 > r2

    def test_retention_increases_with_strength(self):
        r1 = forgetting_curve(10, 1)
        r2 = forgetting_curve(10, 10)
        assert r2 > r1


class TestMemoryBankBackendInit:
    def test_init_creates_backend(self, temp_data_dir):
        backend = MemoryBankBackend(temp_data_dir)
        assert backend.events_store is not None
        assert backend.summaries_store is not None

    def test_init_creates_summaries_file(self, temp_data_dir):
        backend = MemoryBankBackend(temp_data_dir)
        summaries = backend.summaries_store.read()
        assert "daily_summaries" in summaries
        assert summaries["daily_summaries"] == {}
        assert summaries["overall_summary"] == ""


class TestWriteWithMemory:
    def test_write_adds_memory_metadata(self, backend):
        event_id = backend.write_with_memory({"content": "测试事件"})
        events = backend.events_store.read()
        assert len(events) == 1
        event = events[0]
        assert event["id"] == event_id
        assert event["memory_strength"] == 1
        assert "last_recall_date" in event
        assert "date_group" in event

    def test_write_preserves_existing_fields(self, backend):
        backend.write_with_memory({"content": "测试", "custom_field": "preserved"})
        events = backend.events_store.read()
        assert events[0]["custom_field"] == "preserved"


class TestSearchWithForgetting:
    def test_search_no_embedding_model_returns_keyword(self, backend):
        backend.write_with_memory({"content": "今天天气很好"})
        results = backend.search("天气")
        assert len(results) > 0
        assert "天气" in results[0]["content"]

    def test_search_empty_events(self, backend):
        results = backend.search("测试")
        assert results == []

    def test_search_returns_top_k(self, backend):
        for i in range(10):
            backend.write_with_memory({"content": f"事件{i}关于天气"})
        results = backend.search("天气")
        assert len(results) <= 3


class TestRecallStrengthening:
    def test_search_increases_memory_strength(self, backend):
        backend.write_with_memory({"content": "重要的会议"})
        backend.search("会议")
        events = backend.events_store.read()
        assert events[0]["memory_strength"] == 2

    def test_search_updates_only_matched_events(self, backend):
        backend.write_with_memory({"content": "关于天气的事件"})
        backend.write_with_memory({"content": "关于会议的事件"})
        backend.search("天气")
        events = backend.events_store.read()
        weather_event = [e for e in events if "天气" in e["content"]][0]
        meeting_event = [e for e in events if "会议" in e["content"]][0]
        assert weather_event["memory_strength"] == 2
        assert meeting_event["memory_strength"] == 1


class TestHierarchicalSummarization:
    def test_summarize_trigger_threshold(self, temp_data_dir, mock_chat_model):
        backend = MemoryBankBackend(temp_data_dir, chat_model=mock_chat_model)
        for i in range(DAILY_SUMMARY_THRESHOLD):
            backend.write_with_memory({"content": f"事件{i}"})
        summaries = backend.summaries_store.read()
        today = backend.events_store.read()[0]["date_group"]
        assert today in summaries["daily_summaries"]
        assert mock_chat_model.generate.called

    def test_no_summary_below_threshold(self, temp_data_dir, mock_chat_model):
        backend = MemoryBankBackend(temp_data_dir, chat_model=mock_chat_model)
        for i in range(DAILY_SUMMARY_THRESHOLD - 1):
            backend.write_with_memory({"content": f"事件{i}"})
        summaries = backend.summaries_store.read()
        assert len(summaries["daily_summaries"]) == 0
        assert not mock_chat_model.generate.called

    def test_overall_summary_trigger(self, temp_data_dir, mock_chat_model):
        from app.memory.memory_bank import OVERALL_SUMMARY_THRESHOLD

        mock_chat_model.generate.return_value = "总体摘要"
        backend = MemoryBankBackend(temp_data_dir, chat_model=mock_chat_model)
        summaries = backend.summaries_store.read()
        for i in range(OVERALL_SUMMARY_THRESHOLD):
            date_group = f"2026-03-{20 + i:02d}"
            summaries["daily_summaries"][date_group] = {
                "content": f"每日摘要{i}",
                "memory_strength": 1,
                "last_recall_date": date_group,
            }
        backend.summaries_store.write(summaries)
        backend._update_overall_summary(summaries["daily_summaries"])
        updated = backend.summaries_store.read()
        assert updated["overall_summary"] == "总体摘要"
        assert mock_chat_model.generate.called

    def test_summaries_included_in_search(self, temp_data_dir, mock_chat_model):
        mock_chat_model.generate.return_value = "今天讨论了项目进度"
        backend = MemoryBankBackend(temp_data_dir, chat_model=mock_chat_model)
        for i in range(DAILY_SUMMARY_THRESHOLD):
            backend.write_with_memory({"content": f"事件{i}关于项目"})
        results = backend.search("讨论了")
        sources = [r.get("_source") for r in results]
        assert "daily_summary" in sources


class TestWriteInteraction:
    def test_write_interaction_creates_record(self, backend):
        interaction_id = backend.write_interaction("提醒我开会", "好的")
        interactions = backend.interactions_store.read()
        assert len(interactions) == 1
        assert interactions[0]["id"] == interaction_id
        assert interactions[0]["query"] == "提醒我开会"
        assert interactions[0]["response"] == "好的"
        assert interactions[0]["memory_strength"] == 1
        assert interactions[0]["event_id"] is not None

    def test_write_interaction_creates_event(self, backend):
        backend.write_interaction("提醒我开会", "好的")
        events = backend.events_store.read()
        assert len(events) == 1
        assert events[0]["interaction_ids"] == [
            backend.interactions_store.read()[0]["id"]
        ]
        assert events[0]["content"] == "提醒我开会"
        assert "updated_at" in events[0]

    def test_write_interaction_with_event_type(self, backend):
        backend.write_interaction("提醒我开会", "好的", event_type="meeting")
        events = backend.events_store.read()
        assert events[0]["type"] == "meeting"

    def test_write_interaction_returns_id(self, backend):
        interaction_id = backend.write_interaction("测试", "回复")
        assert isinstance(interaction_id, str)
        assert len(interaction_id) > 0


class TestEventAggregation:
    def test_first_interaction_creates_new_event(self, backend):
        iid = backend.write_interaction("提醒我明天上午开会", "好的")
        interactions = backend.interactions_store.read()
        assert interactions[0]["event_id"] != ""
        events = backend.events_store.read()
        assert len(events) == 1
        assert iid in events[0]["interaction_ids"]

    def test_similar_interaction_appends_to_event(self, backend):
        backend.write_interaction("提醒我明天上午开会", "好的")
        backend.write_interaction("明天下午也有会议", "已更新")
        events = backend.events_store.read()
        assert len(events) == 1
        assert len(events[0]["interaction_ids"]) == 2

    def test_different_interaction_creates_new_event(self, backend):
        backend.write_interaction("提醒我明天开会", "好的")
        backend.write_interaction("今天天气怎么样", "晴天")
        events = backend.events_store.read()
        assert len(events) == 2
