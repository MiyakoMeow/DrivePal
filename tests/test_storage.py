"""存储层测试（多用户版）。"""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.memory.memory_bank import MemoryBankStore
from app.memory.schemas import MemoryEvent
from app.storage.init_data import init_storage
from app.storage.toml_store import TOMLStore

pytestmark = [pytest.mark.embedding]


@pytest.fixture
def mock_store(tmp_path: Path) -> MemoryBankStore:
    emb = AsyncMock(spec=["encode", "batch_encode"])
    emb.encode = AsyncMock(return_value=[0.1] * 1536)
    emb.batch_encode = AsyncMock(side_effect=lambda texts: [[0.1] * 1536 for _ in texts])
    chat = AsyncMock(spec=["generate"])
    chat.generate = AsyncMock(return_value="summary")
    return MemoryBankStore(tmp_path, emb, chat)


async def test_events_persist_across_instances(tmp_path: Path) -> None:
    """验证创建新 MemoryBankStore 实例时事件持久化。"""
    init_storage(tmp_path)
    emb = AsyncMock(spec=["encode", "batch_encode"])
    emb.encode = AsyncMock(return_value=[0.1] * 1536)
    emb.batch_encode = AsyncMock(side_effect=lambda texts: [[0.1] * 1536 for _ in texts])
    chat = AsyncMock(spec=["generate"])
    chat.generate = AsyncMock(return_value="summary")

    s1 = MemoryBankStore(tmp_path, emb, chat)
    await s1.write("user_1", MemoryEvent(content="项目进度会议", type="meeting"))

    s2 = MemoryBankStore(tmp_path, emb, chat)
    events = await s2.get_history("user_1")
    assert len(events) >= 1
    assert "项目进度会议" in events[-1].content


async def test_write_interaction_receives_original_query(mock_store: MemoryBankStore) -> None:
    """验证 write_interaction 收到的是原始用户查询而非中间结果。"""
    original_query = "明天下午三点有个会议"
    _result = await mock_store.write_interaction("user_1", original_query, "好的，已记录")
    events = await mock_store.get_history("user_1")
    assert len(events) >= 1
    stored = events[-1]
    assert original_query in stored.content


async def test_get_event_type_returns_none_for_missing(mock_store: MemoryBankStore) -> None:
    """验证 get_event_type 对不存在的 ID 返回 None。"""
    event_type = await mock_store.get_event_type("user_1", "nonexistent_id")
    assert event_type is None
