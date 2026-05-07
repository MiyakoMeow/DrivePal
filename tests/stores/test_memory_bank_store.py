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


@pytest.mark.asyncio
async def test_purge_forgotten_removes_from_index():
    """验证 _purge_forgotten 从 FAISS 索引移除已遗忘条目。"""
    with tempfile.TemporaryDirectory() as tmp:
        emb = AsyncMock(spec=["encode"])
        emb.encode = AsyncMock(return_value=[0.1] * 1536)
        s = MemoryBankStore(Path(tmp), embedding_model=emb)
        await s.write_interaction("hello", "world")
        await s.write_interaction("test2", "data2")
        assert s._index.total == 2
        # 标记第一条为 forgotten
        s._index.get_metadata()[0]["forgotten"] = True
        # 第一次调用：应成功移除
        result = await s._purge_forgotten(s._index.get_metadata())
        assert result is True
        assert s._index.total == 1
        # 第二次调用：节流跳过，无操作
        result = await s._purge_forgotten(s._index.get_metadata())
        assert result is False
        assert s._index.total == 1


@pytest.mark.asyncio
async def test_write_parses_multi_speaker_content():
    """验证 write 解析多行发言格式。"""
    with tempfile.TemporaryDirectory() as tmp:
        emb = AsyncMock(spec=["encode"])
        emb.encode = AsyncMock(return_value=[0.1] * 1536)
        s = MemoryBankStore(Path(tmp), embedding_model=emb)
        content = "Gary: set seat to 45\nPatricia: set AC to 22"
        event = MemoryEvent(content=content, type="reminder")
        eid = await s.write(event)
        assert eid
        meta = s._index.get_metadata()
        assert len(meta) >= 1
        # 配对模式下 2 行 → 1 条向量，且 speakers 包含双方
        assert meta[0]["speakers"] == ["Gary", "Patricia"]


@pytest.mark.asyncio
async def test_write_interaction_with_user_name():
    """验证 write_interaction 支持指定发言者姓名。"""
    with tempfile.TemporaryDirectory() as tmp:
        emb = AsyncMock(spec=["encode"])
        emb.encode = AsyncMock(return_value=[0.1] * 1536)
        s = MemoryBankStore(Path(tmp), embedding_model=emb)
        result = await s.write_interaction(
            "set seat to 45",
            "seat set to 45",
            user_name="Gary",
        )
        assert result.event_id
        meta = s._index.get_metadata()
        assert len(meta) >= 1
        assert any("Gary" in entry.get("speakers", []) for entry in meta)
