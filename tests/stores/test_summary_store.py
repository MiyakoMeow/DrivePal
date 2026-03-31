"""Tests for SummaryStore."""

from collections.abc import Callable
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

from app.memory.schemas import MemoryEvent, SearchResult
from app.memory.stores.summary_store import SummaryStore


def _mock_chat_model(return_value: str = "mock summary") -> MagicMock:
    """Create a mock chat model for testing."""
    model = MagicMock()

    def _fake_generate_with_tools(**kwargs: dict) -> str:
        tool_executor = cast("Callable[[str, dict], str]", kwargs.get("tool_executor"))
        if tool_executor:
            tool_executor("memory_update", {"new_memory": return_value})
        return return_value

    model.generate_with_tools.side_effect = _fake_generate_with_tools
    return model


def test_write_returns_event_id(tmp_path: Path) -> None:
    """Test that write returns a non-empty event ID."""
    store = SummaryStore(tmp_path)
    event_id = store.write(MemoryEvent(content="test"))
    assert isinstance(event_id, str) and len(event_id) > 0


def test_search_returns_empty_when_no_summary(tmp_path: Path) -> None:
    """Test search returns empty when no summary exists."""
    store = SummaryStore(tmp_path)
    assert store.search("query") == []


def test_search_returns_summary_as_single_result(tmp_path: Path) -> None:
    """Test search returns summary as single result."""
    store = SummaryStore(tmp_path, chat_model=_mock_chat_model())
    store.write(MemoryEvent(content="event1"))
    store.write(MemoryEvent(content="event2"))
    results = store.search("anything")
    assert len(results) == 1
    assert isinstance(results[0], SearchResult)
    assert results[0].source == "summary"


def test_get_history_returns_events(tmp_path: Path) -> None:
    """Test get_history returns written events."""
    store = SummaryStore(tmp_path)
    store.write(MemoryEvent(content="event1"))
    store.write(MemoryEvent(content="event2"))
    history = store.get_history(limit=10)
    assert len(history) == 2
    assert all(isinstance(e, MemoryEvent) for e in history)


def test_get_history_respects_limit(tmp_path: Path) -> None:
    """Test get_history respects limit parameter."""
    store = SummaryStore(tmp_path)
    for i in range(5):
        store.write(MemoryEvent(content=f"event{i}"))
    assert len(store.get_history(limit=3)) == 3


def test_write_interaction_records_event(tmp_path: Path) -> None:
    """Test write_interaction records an event."""
    store = SummaryStore(tmp_path, chat_model=_mock_chat_model())
    event_id = store.write_interaction("query", "response")
    assert isinstance(event_id, str) and len(event_id) > 0
    history = store.get_history(limit=10)
    assert len(history) == 1


def test_update_feedback_does_not_crash(tmp_path: Path) -> None:
    """Test update_feedback does not raise an exception."""
    store = SummaryStore(tmp_path)
    event_id = store.write(MemoryEvent(content="event"))
    store.update_feedback(event_id, MagicMock(event_id=event_id, action="accept"))


def test_get_history_limit_zero(tmp_path: Path) -> None:
    """Test get_history with limit=0 returns empty list."""
    store = SummaryStore(tmp_path)
    store.write(MemoryEvent(content="event1"))
    assert store.get_history(limit=0) == []


def test_get_history_limit_negative(tmp_path: Path) -> None:
    """Test get_history with negative limit returns empty list."""
    store = SummaryStore(tmp_path)
    store.write(MemoryEvent(content="event1"))
    assert store.get_history(limit=-1) == []
