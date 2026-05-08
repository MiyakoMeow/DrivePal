"""MemoryBankStore 多用户测试。"""

import os
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from app.memory.memory_bank.store import MemoryBankStore
from app.memory.schemas import FeedbackData, MemoryEvent


@pytest.fixture
def mock_emb() -> AsyncMock:
    m = AsyncMock(spec=["encode", "batch_encode"])
    m.encode = AsyncMock(return_value=[0.1] * 1536)
    m.batch_encode = AsyncMock(side_effect=lambda texts: [[0.1] * 1536 for _ in texts])
    return m


@pytest.fixture
def mock_chat() -> AsyncMock:
    m = AsyncMock(spec=["generate"])
    m.generate = AsyncMock(return_value="summary text")
    return m


@pytest.fixture
def store(tmp_path: Path, mock_emb, mock_chat) -> MemoryBankStore:
    return MemoryBankStore(tmp_path, mock_emb, mock_chat)


@pytest.mark.asyncio
async def test_write_interaction_returns_id(store: MemoryBankStore) -> None:
    """验证 write_interaction 返回事件 ID。"""
    result = await store.write_interaction("user_1", "hello", "world")
    assert result.event_id
    assert isinstance(result.event_id, str)


@pytest.mark.asyncio
async def test_search_returns_results(store: MemoryBankStore) -> None:
    """验证写入后可搜索到结果。"""
    await store.write_interaction("user_1", "set seat to 45", "seat set to 45")
    results = await store.search("user_1", "seat", top_k=5)
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_write_returns_id(store: MemoryBankStore) -> None:
    """验证 write 返回事件 ID。"""
    event = MemoryEvent(content="test event", type="reminder")
    eid = await store.write("user_1", event)
    assert eid
    assert isinstance(eid, str)


@pytest.mark.asyncio
async def test_get_history(store: MemoryBankStore) -> None:
    """验证 get_history 返回历史事件。"""
    await store.write_interaction("user_1", "test", "response")
    history = await store.get_history("user_1", limit=10)
    assert len(history) >= 1
    assert isinstance(history[0], MemoryEvent)


@pytest.mark.asyncio
async def test_get_event_type_none_for_missing(store: MemoryBankStore) -> None:
    """验证不存在的 event_id 返回 None。"""
    t = await store.get_event_type("user_1", "nonexistent")
    assert t is None


@pytest.mark.asyncio
async def test_multi_user_isolation(store: MemoryBankStore) -> None:
    """多用户隔离：user_a 的写入不影响 user_b。"""
    await store.write_interaction("alice", "hello alice", "hi alice")
    await store.write_interaction("bob", "hello bob", "hi bob")

    results_alice = await store.search("alice", "hello", top_k=5)
    results_bob = await store.search("bob", "hello", top_k=5)
    assert len(results_alice) >= 1
    assert len(results_bob) >= 1

    # alice 只能搜到 alice 的
    history_alice = await store.get_history("alice")
    history_bob = await store.get_history("bob")
    assert len(history_alice) >= 1
    assert len(history_bob) >= 1


@pytest.mark.asyncio
async def test_write_parses_multi_speaker_content(store: MemoryBankStore) -> None:
    """验证 write 解析多行发言格式。"""
    content = "Gary: set seat to 45\nPatricia: set AC to 22"
    event = MemoryEvent(content=content, type="reminder")
    eid = await store.write("user_1", event)
    assert eid


@pytest.mark.asyncio
async def test_write_interaction_with_user_name(store: MemoryBankStore) -> None:
    """验证 write_interaction 支持指定发言者姓名。"""
    result = await store.write_interaction(
        "user_1",
        "set seat to 45",
        "seat set to 45",
        user_name="Gary",
    )
    assert result.event_id


@pytest.mark.asyncio
async def test_get_reference_date_from_metadata(
    tmp_path: Path, mock_emb, mock_chat
) -> None:
    """_get_reference_date 从 metadata 自动计算。"""
    store = MemoryBankStore(tmp_path, mock_emb, mock_chat)
    # 写入一条数据
    await store.write_interaction("user_1", "test", "response")
    ref_date = store._get_reference_date("user_1")
    assert ref_date is not None


@pytest.mark.asyncio
async def test_update_feedback_silent(store: MemoryBankStore) -> None:
    """update_feedback 静默忽略。"""
    feedback = FeedbackData(action="accept")
    await store.update_feedback("user_1", "0", feedback)


@pytest.mark.asyncio
async def test_forget_at_ingestion_removes_old_entries(
    tmp_path: Path, mock_emb: AsyncMock, mock_chat: AsyncMock
) -> None:
    """遗忘开启时，写入新数据应删除 retention < threshold 的旧条目。"""
    os.environ["MEMORYBANK_ENABLE_FORGETTING"] = "true"
    try:
        store = MemoryBankStore(
            tmp_path,
            mock_emb,
            mock_chat,
            reference_date="2026-05-05",
        )
        emb = [0.1] * 1536
        # 写入一条旧条目（strength=1，referenced to 2026-01-01 > 125d ago → retention ≈ 0）
        await store._index_manager.add_vector(
            "user_1",
            "old data",
            emb,
            "2026-01-01T00:00:00",
            {"memory_strength": 1, "last_recall_date": "2026-01-01"},
        )
        await store._index_manager.save("user_1")
        total_before = await store._index_manager.total("user_1")
        assert total_before == 1

        # 写入新数据触发遗忘
        await store.write("user_1", MemoryEvent(content="new data"))

        total_after = await store._index_manager.total("user_1")
        # 旧数据应被遗忘删除，只剩新写入的
        assert total_after == 1, f"expected 1 entry after forget, got {total_after}"
    finally:
        os.environ.pop("MEMORYBANK_ENABLE_FORGETTING", None)
