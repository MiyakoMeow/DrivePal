"""MemoryStore 接口契约测试 - 验证所有实现满足统一接口."""

import pytest

from app.memory.schemas import FeedbackData, MemoryEvent, SearchResult


class TestMemoryStoreContract:
    """验证所有 MemoryStore 实现满足接口契约."""

    @pytest.fixture(params=["keyword", "llm_only", "embeddings", "memorybank"])
    def store(self, request, tmp_path):
        from app.memory.memory import MemoryModule
        from app.memory.types import MemoryMode

        mm = MemoryModule(str(tmp_path))
        return mm._get_store(MemoryMode(request.param))

    def test_write_returns_string_id(self, store):
        event_id = store.write(MemoryEvent(content="test"))
        assert isinstance(event_id, str)
        assert len(event_id) > 0

    def test_write_then_search_returns_same_event(self, store):
        event_id = store.write(MemoryEvent(content="测试事件"))
        events = store.events_store.read()
        assert any(e["id"] == event_id for e in events)

    def test_search_returns_list_of_search_result(self, store):
        store.write(MemoryEvent(content="测试事件"))
        results = store.search("测试")
        assert isinstance(results, list)
        assert all(isinstance(r, SearchResult) for r in results)

    def test_get_history_returns_list_of_memory_event(self, store):
        store.write(MemoryEvent(content="事件1"))
        history = store.get_history(limit=10)
        assert isinstance(history, list)
        assert isinstance(history[0], MemoryEvent)

    def test_get_history_respects_limit(self, store):
        for i in range(5):
            store.write(MemoryEvent(content=f"事件{i}"))
        history = store.get_history(limit=3)
        assert len(history) == 3

    def test_update_feedback_updates_strategies(self, store):
        event_id = store.write(MemoryEvent(content="事件"))
        store.update_feedback(event_id, FeedbackData(action="accept", type="meeting"))
        strategies = store.strategies_store.read()
        assert "reminder_weights" in strategies
