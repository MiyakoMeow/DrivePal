from app.memory.memory import MemoryModule
from app.storage.init_data import init_storage


def test_events_persist_across_instances(tmp_path):
    init_storage(str(tmp_path))
    m1 = MemoryModule(str(tmp_path))
    m1.write({"content": "项目进度会议", "type": "meeting"})
    m2 = MemoryModule(str(tmp_path))
    events = m2.events_store.read()
    assert len(events) == 1
    assert events[0]["content"] == "项目进度会议"


def test_feedback_updates_strategies(tmp_path):
    from app.storage.json_store import JSONStore

    memory = MemoryModule(str(tmp_path))
    event_id = memory.write({"content": "团队周会", "type": "meeting"})
    memory.update_feedback(event_id, {"action": "accept", "type": "meeting"})
    strategies = JSONStore(str(tmp_path), "strategies.json", dict).read()
    assert strategies["reminder_weights"]["meeting"] == 0.6


def test_ignore_feedback_decreases_weight(tmp_path):
    from app.storage.json_store import JSONStore

    memory = MemoryModule(str(tmp_path))
    event_id = memory.write({"content": "无关提醒", "type": "general"})
    memory.update_feedback(event_id, {"action": "ignore", "type": "general"})
    strategies = JSONStore(str(tmp_path), "strategies.json", dict).read()
    assert strategies["reminder_weights"]["general"] < 0.5


def test_feedback_history_appended(tmp_path):
    from app.storage.json_store import JSONStore

    memory = MemoryModule(str(tmp_path))
    eid1 = memory.write({"content": "会议A", "type": "meeting"})
    eid2 = memory.write({"content": "会议B", "type": "meeting"})
    memory.update_feedback(eid1, {"action": "accept", "type": "meeting"})
    memory.update_feedback(eid2, {"action": "ignore", "type": "meeting"})
    feedback = JSONStore(str(tmp_path), "feedback.json", list).read()
    assert len(feedback) == 2
