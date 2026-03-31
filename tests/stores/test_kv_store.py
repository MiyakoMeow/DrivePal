"""Tests for KVStore."""

from pathlib import Path
from unittest.mock import MagicMock

from app.memory.schemas import MemoryEvent
from app.memory.stores.kv_store import KVStore


def _mock_chat_model() -> MagicMock:
    """Create a mock chat model for testing."""
    model = MagicMock()
    model.generate_with_tools.return_value = "done"
    return model


def test_write_returns_event_id(tmp_path: Path) -> None:
    """Test that write returns a non-empty event ID."""
    store = KVStore(tmp_path)
    event_id = store.write(MemoryEvent(content="test"))
    assert isinstance(event_id, str) and len(event_id) > 0


def test_search_empty_store(tmp_path: Path) -> None:
    """Test search returns empty list when store is empty."""
    store = KVStore(tmp_path)
    assert store.search("query") == []


def test_search_finds_kv_entry(tmp_path: Path) -> None:
    """Test search finds KV entry by key."""
    store = KVStore(tmp_path)
    state = store._read_state()
    state["kv_data"] = {"Gary_seat_position": "forward", "Patricia_temp": "22"}
    store._write_state(state)
    results = store.search("Gary_seat")
    assert len(results) == 1
    assert "Gary_seat_position" in results[0].event["content"]


def test_search_fuzzy_match(tmp_path: Path) -> None:
    """Test search performs fuzzy matching on keys."""
    store = KVStore(tmp_path)
    state = store._read_state()
    state["kv_data"] = {"Gary_instrument_panel_color": "green"}
    store._write_state(state)
    results = store.search("panel")
    assert len(results) == 1


def test_search_no_match(tmp_path: Path) -> None:
    """Test search returns empty when no match found."""
    store = KVStore(tmp_path)
    state = store._read_state()
    state["kv_data"] = {"Gary_temp": "22"}
    store._write_state(state)
    results = store.search("nonexistent")
    assert len(results) == 0


def test_get_history_returns_events(tmp_path: Path) -> None:
    """Test get_history returns written events."""
    store = KVStore(tmp_path)
    store.write(MemoryEvent(content="event1"))
    store.write(MemoryEvent(content="event2"))
    history = store.get_history(limit=10)
    assert len(history) == 2


def test_write_interaction_records_event(tmp_path: Path) -> None:
    """Test write_interaction records an event."""
    store = KVStore(tmp_path, chat_model=_mock_chat_model())
    event_id = store.write_interaction("query", "response", event_type="custom_type")
    assert isinstance(event_id, str) and len(event_id) > 0
    history = store.get_history(limit=1)
    assert len(history) == 1
    assert history[0].content == "query"
    assert history[0].type == "custom_type"
    assert history[0].description == "response"


def test_update_feedback_does_not_crash(tmp_path: Path) -> None:
    """Test update_feedback does not raise an exception."""
    store = KVStore(tmp_path)
    event_id = store.write(MemoryEvent(content="event"))
    store.update_feedback(event_id, MagicMock(event_id=event_id, action="ignore"))


def test_search_empty_string_query(tmp_path: Path) -> None:
    """Test search with empty string returns empty results."""
    store = KVStore(tmp_path)
    state = store._read_state()
    state["kv_data"] = {"Gary_temp": "22"}
    store._write_state(state)
    results = store.search("")
    assert len(results) == 0


def test_get_history_limit_zero(tmp_path: Path) -> None:
    """Test get_history with limit=0 returns empty list."""
    store = KVStore(tmp_path)
    store.write(MemoryEvent(content="event1"))
    assert store.get_history(limit=0) == []


def test_get_history_limit_negative(tmp_path: Path) -> None:
    """Test get_history with negative limit returns empty list."""
    store = KVStore(tmp_path)
    store.write(MemoryEvent(content="event1"))
    assert store.get_history(limit=-1) == []


def test_search_respects_top_k(tmp_path: Path) -> None:
    """Test search respects top_k parameter."""
    store = KVStore(tmp_path)
    state = store._read_state()
    state["kv_data"] = {
        "Gary_temp": "22",
        "Patricia_temp": "25",
        "Gary_panel": "green",
    }
    store._write_state(state)
    results = store.search("Gary", top_k=2)
    assert len(results) == 2
