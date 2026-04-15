"""MemoryBankStore 测试 - 仅存储级别测试."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.memory.schemas import InteractionResult, MemoryEvent
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


class TestWriteBatch:
    """write_batch 功能测试."""

    async def test_write_batch_progress_fn_called(
        self,
        store: MemoryBankStore,
    ) -> None:
        """验证 write_batch 透传 progress_fn 回调."""
        events = [
            MemoryEvent(content="事件1"),
            MemoryEvent(content="事件2"),
        ]
        calls: list[tuple[int, int]] = []
        await store.write_batch(
            events, progress_fn=lambda cur, total: calls.append((cur, total))
        )
        assert len(calls) == len(events)
        assert calls[0] == (1, len(events))
        assert calls[1] == (2, len(events))


def test_embedding_cache_reduces_batch_encode_calls(
    tmp_path: Path,
) -> None:
    """warmup_embeddings 应缓存向量，后续 search 不再调用 batch_encode."""
    mock_embedding = AsyncMock()
    encode_call_count = 0

    async def fake_encode(_text: str) -> list[float]:
        nonlocal encode_call_count
        encode_call_count += 1
        return [0.1] * 10

    async def fake_batch_encode(texts: list[str]) -> list[list[float]]:
        nonlocal encode_call_count
        encode_call_count += len(texts)
        return [[0.1] * 10 for _ in texts]

    mock_embedding.encode = fake_encode
    mock_embedding.batch_encode = fake_batch_encode

    mock_chat = MagicMock()

    store = MemoryBankStore(
        data_dir=tmp_path,
        embedding_model=mock_embedding,
        chat_model=mock_chat,
    )

    event = MemoryEvent(
        id="test_1",
        content="用户喜欢温度22度",
        description="",
        type="general",
        date_group="2024-01-15",
        memory_strength=1,
        last_recall_date="2024-01-15",
    )
    asyncio.run(store.write(event))

    asyncio.run(store.warmup_embeddings())
    count_after_warmup = encode_call_count

    asyncio.run(store.search("温度", top_k=5))

    assert encode_call_count == count_after_warmup + 1
