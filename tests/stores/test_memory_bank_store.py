"""MemoryBankStore MemoryStore Protocol 测试。"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.memory.schemas import MemoryEvent
from app.memory.stores.memory_bank.store import MemoryBankStore


@pytest.fixture
def store():
    """提供 mock embedding 的 MemoryBankStore 实例。"""
    with tempfile.TemporaryDirectory() as tmp:
        emb = AsyncMock(spec=["encode"])
        emb.encode = AsyncMock(return_value=[0.1] * 1536)
        s = MemoryBankStore(Path(tmp), embedding_model=emb)
        yield s


@pytest.mark.asyncio
async def test_write_interaction_returns_id(store):
    """验证 write_interaction 返回事件 ID。"""
    result = await store.write_interaction("hello", "world")
    assert result.event_id
    assert isinstance(result.event_id, str)


@pytest.mark.asyncio
async def test_search_returns_results(store):
    """验证写入后可搜索到结果。"""
    await store.write_interaction("set seat to 45", "seat set to 45")
    results = await store.search("seat", top_k=5)
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_write_returns_id(store):
    """验证 write 返回事件 ID。"""
    event = MemoryEvent(content="test event", type="reminder")
    eid = await store.write(event)
    assert eid
    assert isinstance(eid, str)


@pytest.mark.asyncio
async def test_get_history(store):
    """验证 get_history 返回历史事件。"""
    await store.write_interaction("test", "response")
    history = await store.get_history(limit=10)
    assert len(history) >= 1
    assert isinstance(history[0], MemoryEvent)


@pytest.mark.asyncio
async def test_get_event_type_none_for_missing(store):
    """验证不存在的 event_id 返回 None。"""
    t = await store.get_event_type("nonexistent")
    assert t is None
