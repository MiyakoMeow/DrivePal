"""存储层测试."""

from pathlib import Path

import pytest

from app.memory.memory import MemoryModule
from app.memory.schemas import FeedbackData, MemoryEvent
from app.storage.init_data import init_storage
from app.storage.toml_store import TOMLStore

pytestmark = [pytest.mark.embedding]

# 接受反馈后 meeting 策略权重目标值
MEETING_WEIGHT_AFTER_ACCEPT = 0.6
# 忽略反馈后 general 策略权重上限
GENERAL_WEIGHT_AFTER_IGNORE_MAX = 0.5
# 反馈历史记录数量
FEEDBACK_HISTORY_COUNT = 2


async def test_events_persist_across_instances(tmp_path: Path) -> None:
    """验证创建新 MemoryModule 实例时事件持久化."""
    init_storage(tmp_path)
    m1 = MemoryModule(tmp_path)
    await m1.write(MemoryEvent(content="项目进度会议", type="meeting"))
    m2 = MemoryModule(tmp_path)
    events = await m2.get_history()
    assert len(events) == 1
    assert events[0].content == "项目进度会议"


async def test_ignore_feedback_decreases_weight(tmp_path: Path) -> None:
    """验证忽略反馈会降低对应策略权重."""
    memory = MemoryModule(tmp_path)
    event_id = await memory.write(MemoryEvent(content="无关提醒", type="general"))
    await memory.update_feedback(
        event_id,
        FeedbackData(action="ignore", type="general"),
    )
    strategies = await TOMLStore(tmp_path, Path("strategies.toml"), dict).read()
    assert strategies["reminder_weights"]["general"] < GENERAL_WEIGHT_AFTER_IGNORE_MAX


@pytest.mark.llm
async def test_feedback_history_appended(tmp_path: Path) -> None:
    """验证每条反馈记录都追加到反馈历史.

    注意：此测试写入2个事件，会触发 DAILY_SUMMARY_THRESHOLD=2，
    从而调用 LLM 生成摘要，因此需要 @pytest.mark.llm 标记。
    """
    memory = MemoryModule(tmp_path)
    eid1 = await memory.write(MemoryEvent(content="会议A", type="meeting"))
    eid2 = await memory.write(MemoryEvent(content="会议B", type="meeting"))
    await memory.update_feedback(eid1, FeedbackData(action="accept", type="meeting"))
    await memory.update_feedback(eid2, FeedbackData(action="ignore", type="meeting"))
    feedback = await TOMLStore(tmp_path, Path("feedback.toml"), list).read()
    assert len(feedback) == FEEDBACK_HISTORY_COUNT


async def test_write_interaction_receives_original_query(tmp_path: Path) -> None:
    """验证 write_interaction 收到的是原始用户查询而非中间结果."""
    init_storage(tmp_path)
    memory = MemoryModule(tmp_path)
    original_query = "明天下午三点有个会议"
    _result = await memory.write_interaction(original_query, "好的，已记录")
    events = await memory.get_history()
    assert len(events) >= 1
    stored = events[-1]
    assert original_query in stored.content


async def test_feedback_via_event_type_lookup(tmp_path: Path) -> None:
    """验证通过 event_id 查找事件类型后更新策略权重."""
    memory = MemoryModule(tmp_path)
    result = await memory.write_interaction(
        "团队周会",
        "好的",
        event_type="meeting",
    )
    event_type = await memory.get_event_type(result.event_id)
    assert event_type == "meeting"
    await memory.update_feedback(
        result.event_id,
        FeedbackData(action="accept", type=event_type or "default"),
    )
    strategies = await TOMLStore(tmp_path, Path("strategies.toml"), dict).read()
    assert strategies["reminder_weights"]["meeting"] == pytest.approx(0.6)


async def test_get_event_type_returns_none_for_missing(tmp_path: Path) -> None:
    """验证 get_event_type 对不存在的 ID 返回 None."""
    memory = MemoryModule(tmp_path)
    event_type = await memory.get_event_type("nonexistent_id")
    assert event_type is None
