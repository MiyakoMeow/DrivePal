"""KeywordMemoryStore 测试."""

import pytest
from app.memory.schemas import FeedbackData, MemoryEvent, SearchResult
from app.memory.stores.keyword_store import KeywordMemoryStore


@pytest.fixture
def store(tmp_path: str) -> KeywordMemoryStore:
    """Create a KeywordMemoryStore for testing."""
    return KeywordMemoryStore(str(tmp_path))


class TestKeywordMemoryStore:
    """Tests for KeywordMemoryStore class."""

    def test_write_returns_event_id(self, store: KeywordMemoryStore) -> None:
        """Test that write returns a string event ID."""
        event_id = store.write(MemoryEvent(content="测试事件"))
        assert isinstance(event_id, str)

    def test_write_then_search_returns_event(self, store: KeywordMemoryStore) -> None:
        """Test that write followed by search returns the event."""
        event_id = store.write(MemoryEvent(content="测试事件"))
        results = store.search("测试")
        assert len(results) == 1
        assert isinstance(results[0], SearchResult)
        assert results[0].event["id"] == event_id

    def test_search_case_insensitive(self, store: KeywordMemoryStore) -> None:
        """Test that search is case insensitive."""
        store.write(MemoryEvent(content="Hello World"))
        results = store.search("hello")
        assert len(results) == 1

    def test_search_no_match(self, store: KeywordMemoryStore) -> None:
        """Test that search returns empty when no match."""
        store.write(MemoryEvent(content="测试事件"))
        results = store.search("不存在")
        assert len(results) == 0

    def test_search_matches_description(self, store: KeywordMemoryStore) -> None:
        """Test that search matches description field."""
        store.write(MemoryEvent(content="主内容", description="辅助描述"))
        results = store.search("辅助")
        assert len(results) == 1

    def test_get_history_returns_recent_events(self, store: KeywordMemoryStore) -> None:
        """Test that get_history returns most recent events."""
        for i in range(5):
            store.write(MemoryEvent(content=f"事件{i}"))
        history = store.get_history(limit=3)
        assert len(history) == 3
        assert all(isinstance(e, MemoryEvent) for e in history)

    def test_update_feedback_accept(self, store: KeywordMemoryStore) -> None:
        """Test that accept feedback increases reminder weight."""
        event_id = store.write(MemoryEvent(content="事件"))
        store.update_feedback(event_id, FeedbackData(action="accept", type="meeting"))
        strategies = store.strategies_store.read()
        assert strategies["reminder_weights"]["meeting"] > 0.5

    def test_update_feedback_ignore(self, store: KeywordMemoryStore) -> None:
        """Test that ignore feedback decreases reminder weight."""
        event_id = store.write(MemoryEvent(content="事件"))
        store.update_feedback(event_id, FeedbackData(action="ignore", type="meeting"))
        strategies = store.strategies_store.read()
        assert strategies["reminder_weights"]["meeting"] < 0.5

    def test_write_interaction_stores_query_as_description(
        self, store: KeywordMemoryStore
    ) -> None:
        """Test that write_interaction stores query as description."""
        store.write_interaction("查询内容", "响应内容")
        history = store.get_history(limit=1)
        assert history[0].content == "查询内容"
        assert history[0].description == "响应内容"
