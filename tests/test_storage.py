"""存储层测试."""

from pathlib import Path

from app.memory.memory import MemoryModule
from app.memory.schemas import FeedbackData, MemoryEvent
from app.storage.init_data import init_storage


async def test_events_persist_across_instances(tmp_path: Path) -> None:
    """验证创建新 MemoryModule 实例时事件持久化."""
    init_storage(tmp_path)
    m1 = MemoryModule(tmp_path)
    await m1.write(MemoryEvent(content="项目进度会议", type="meeting"))
    m2 = MemoryModule(tmp_path)
    events = await m2.get_history()
    assert len(events) == 1
    assert events[0].content == "项目进度会议"


async def test_feedback_updates_strategies(tmp_path: Path) -> None:
    """验证接受反馈会增加对应策略权重."""
    from app.storage.toml_store import TOMLStore

    memory = MemoryModule(tmp_path)
    event_id = await memory.write(MemoryEvent(content="团队周会", type="meeting"))
    await memory.update_feedback(
        event_id, FeedbackData(action="accept", type="meeting")
    )
    strategies = await TOMLStore(tmp_path, Path("strategies.toml"), dict).read()
    assert strategies["reminder_weights"]["meeting"] == 0.6


async def test_ignore_feedback_decreases_weight(tmp_path: Path) -> None:
    """验证忽略反馈会降低对应策略权重."""
    from app.storage.toml_store import TOMLStore

    memory = MemoryModule(tmp_path)
    event_id = await memory.write(MemoryEvent(content="无关提醒", type="general"))
    await memory.update_feedback(
        event_id, FeedbackData(action="ignore", type="general")
    )
    strategies = await TOMLStore(tmp_path, Path("strategies.toml"), dict).read()
    assert strategies["reminder_weights"]["general"] < 0.5


async def test_feedback_history_appended(tmp_path: Path) -> None:
    """验证每条反馈记录都追加到反馈历史."""
    from app.storage.toml_store import TOMLStore

    memory = MemoryModule(tmp_path)
    eid1 = await memory.write(MemoryEvent(content="会议A", type="meeting"))
    eid2 = await memory.write(MemoryEvent(content="会议B", type="meeting"))
    await memory.update_feedback(eid1, FeedbackData(action="accept", type="meeting"))
    await memory.update_feedback(eid2, FeedbackData(action="ignore", type="meeting"))
    feedback = await TOMLStore(tmp_path, Path("feedback.toml"), list).read()
    assert len(feedback) == 2
