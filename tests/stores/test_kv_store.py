from pathlib import Path
from unittest.mock import MagicMock

from app.memory.schemas import MemoryEvent
from app.memory.stores.kv_store import KVStore


def _mock_chat_model() -> MagicMock:
    model = MagicMock()
    model.generate_with_tools.return_value = "done"
    return model


def test_write_returns_event_id(tmp_path: Path):
    store = KVStore(tmp_path)
    event_id = store.write(MemoryEvent(content="test"))
    assert isinstance(event_id, str) and len(event_id) > 0


def test_search_empty_store(tmp_path: Path):
    store = KVStore(tmp_path)
    assert store.search("query") == []


def test_search_finds_kv_entry(tmp_path: Path):
    store = KVStore(tmp_path)
    state = store._read_state()
    state["kv_data"] = {"Gary_seat_position": "forward", "Patricia_temp": "22"}
    store._write_state(state)
    results = store.search("Gary_seat")
    assert len(results) >= 1
    assert "Gary_seat_position" in results[0].event["content"]


def test_search_fuzzy_match(tmp_path: Path):
    store = KVStore(tmp_path)
    state = store._read_state()
    state["kv_data"] = {"Gary_instrument_panel_color": "green"}
    store._write_state(state)
    results = store.search("panel")
    assert len(results) >= 1


def test_search_no_match(tmp_path: Path):
    store = KVStore(tmp_path)
    state = store._read_state()
    state["kv_data"] = {"Gary_temp": "22"}
    store._write_state(state)
    results = store.search("nonexistent")
    assert len(results) == 0


def test_get_history_returns_events(tmp_path: Path):
    store = KVStore(tmp_path)
    store.write(MemoryEvent(content="event1"))
    store.write(MemoryEvent(content="event2"))
    history = store.get_history(limit=10)
    assert len(history) == 2


def test_write_interaction_records_event(tmp_path: Path):
    store = KVStore(tmp_path, chat_model=_mock_chat_model())
    event_id = store.write_interaction("query", "response")
    assert isinstance(event_id, str) and len(event_id) > 0


def test_update_feedback_does_not_crash(tmp_path: Path):
    store = KVStore(tmp_path)
    event_id = store.write(MemoryEvent(content="event"))
    store.update_feedback(event_id, MagicMock(event_id=event_id, action="ignore"))
