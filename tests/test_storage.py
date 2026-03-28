"""Tests for the storage layer."""

from app.memory.memory import MemoryModule
from app.memory.schemas import FeedbackData, MemoryEvent
from app.storage.init_data import init_storage
from tests.conftest import SKIP_IF_NO_LLM


@SKIP_IF_NO_LLM
def test_events_persist_across_instances(tmp_path):
    """Verify that events persist when creating a new MemoryModule instance."""
    init_storage(str(tmp_path))
    m1 = MemoryModule(str(tmp_path))
    m1.write(MemoryEvent(content="项目进度会议", type="meeting"))
    m2 = MemoryModule(str(tmp_path))
    events = m2.get_history()
    assert len(events) == 1
    assert events[0].content == "项目进度会议"


@SKIP_IF_NO_LLM
def test_feedback_updates_strategies(tmp_path):
    """Verify that accepting feedback increases the corresponding strategy weight."""
    from app.storage.json_store import JSONStore

    memory = MemoryModule(str(tmp_path))
    event_id = memory.write(MemoryEvent(content="团队周会", type="meeting"))
    memory.update_feedback(event_id, FeedbackData(action="accept", type="meeting"))
    strategies = JSONStore(str(tmp_path), "strategies.json", dict).read()
    assert strategies["reminder_weights"]["meeting"] == 0.6


@SKIP_IF_NO_LLM
def test_ignore_feedback_decreases_weight(tmp_path):
    """Verify that ignoring feedback decreases the corresponding strategy weight."""
    from app.storage.json_store import JSONStore

    memory = MemoryModule(str(tmp_path))
    event_id = memory.write(MemoryEvent(content="无关提醒", type="general"))
    memory.update_feedback(event_id, FeedbackData(action="ignore", type="general"))
    strategies = JSONStore(str(tmp_path), "strategies.json", dict).read()
    assert strategies["reminder_weights"]["general"] < 0.5


@SKIP_IF_NO_LLM
def test_feedback_history_appended(tmp_path):
    """Verify that each feedback entry is appended to the feedback history."""
    from app.storage.json_store import JSONStore

    memory = MemoryModule(str(tmp_path))
    eid1 = memory.write(MemoryEvent(content="会议A", type="meeting"))
    eid2 = memory.write(MemoryEvent(content="会议B", type="meeting"))
    memory.update_feedback(eid1, FeedbackData(action="accept", type="meeting"))
    memory.update_feedback(eid2, FeedbackData(action="ignore", type="meeting"))
    feedback = JSONStore(str(tmp_path), "feedback.json", list).read()
    assert len(feedback) == 2
