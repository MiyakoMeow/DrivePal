"""MemoryBankStore 测试 - 仅存储级别测试."""

from typing import TYPE_CHECKING

import pytest

from app.memory.schemas import InteractionResult
from app.memory.stores.memory_bank import MemoryBankStore

if TYPE_CHECKING:
    from pathlib import Path

# 相似交互聚合后的交互 ID 数量
AGGREGATED_INTERACTION_COUNT = 2
# 聚合范围扩展测试中的最小交互数
MIN_AGGREGATED_INTERACTIONS = 2


@pytest.fixture
def store(tmp_path: Path) -> MemoryBankStore:
    """创建用于测试的 MemoryBankStore."""
    return MemoryBankStore(tmp_path)


class TestWriteInteraction:
    """write_interaction 功能测试."""

    async def test_write_interaction_creates_record(
        self,
        store: MemoryBankStore,
    ) -> None:
        """验证 write_interaction 创建交互记录."""
        result = await store.write_interaction("提醒我开会", "好的")
        assert isinstance(result, InteractionResult)
        assert len(result.event_id) > 0
        assert len(result.interaction_id) > 0
        interactions = await store.interactions_store.read()
        stored_ids = [i["id"] for i in interactions]
        assert result.interaction_id in stored_ids, (
            f"returned id {result.interaction_id} not found in stored {stored_ids}"
        )

    async def test_write_interaction_aggregates_similar(
        self,
        store: MemoryBankStore,
    ) -> None:
        """验证相似交互被聚合."""
        await store.write_interaction("提醒我明天上午开会", "好的")
        await store.write_interaction("明天下午也有会议", "已更新")
        events = await store.events_store.read()
        assert len(events) == 1
        assert len(events[0]["interaction_ids"]) == AGGREGATED_INTERACTION_COUNT

    async def test_write_interaction_aggregates_with_earlier_same_day_event(
        self,
        store: MemoryBankStore,
    ) -> None:
        """验证同日非连续相似交互也能聚合（而非仅最后一条）."""
        await store.write_interaction("明天上午开会讨论项目", "好的")
        await store.write_interaction("明天下午去打球", "已记录")
        await store.write_interaction("明天上午的会议改到十点", "已更新")
        events = await store.events_store.read()
        meeting_events = [
            e
            for e in events
            if "会议" in e.get("content", "") or "开会" in e.get("content", "")
        ]
        assert len(meeting_events) == 1
        assert len(meeting_events[0]["interaction_ids"]) == MIN_AGGREGATED_INTERACTIONS
