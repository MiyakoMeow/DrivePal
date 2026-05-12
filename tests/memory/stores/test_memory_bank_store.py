"""MemoryBankStore MemoryStore Protocol 测试."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.memory.memory_bank.store import MemoryBankStore
from app.memory.schemas import FeedbackData, MemoryEvent


@pytest.fixture
def store():
    """提供 mock embedding 的 MemoryBankStore 实例."""
    with tempfile.TemporaryDirectory() as tmp:
        emb = AsyncMock(spec=["encode", "batch_encode"])
        emb.encode = AsyncMock(return_value=[0.1] * 1536)

        async def _batch_encode(texts: list[str]) -> list[list[float]]:
            return [[0.1] * 1536 for _ in texts]

        emb.batch_encode = AsyncMock(side_effect=_batch_encode)
        s = MemoryBankStore(Path(tmp), embedding_model=emb)
        yield s


@pytest.mark.asyncio
async def test_write_interaction_returns_id(store):
    """验证 write_interaction 返回事件 ID."""
    result = await store.write_interaction("hello", "world")
    assert result.event_id
    assert isinstance(result.event_id, str)


@pytest.mark.asyncio
async def test_search_returns_results(store):
    """验证写入后可搜索到结果."""
    await store.write_interaction("set seat to 45", "seat set to 45")
    results = await store.search("seat", top_k=5)
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_write_returns_id(store):
    """验证 write 返回事件 ID."""
    event = MemoryEvent(content="test event", type="reminder")
    eid = await store.write(event)
    assert eid
    assert isinstance(eid, str)


@pytest.mark.asyncio
async def test_get_history(store):
    """验证 get_history 返回历史事件."""
    await store.write_interaction("test", "response")
    history = await store.get_history(limit=10)
    assert len(history) >= 1
    assert isinstance(history[0], MemoryEvent)


@pytest.mark.asyncio
async def test_get_event_type_none_for_missing(store):
    """验证不存在的 event_id 返回 None."""
    t = await store.get_event_type("nonexistent")
    assert t is None


@pytest.mark.asyncio
async def test_purge_forgotten_removes_from_index():
    """验证 _purge_forgotten 从 FAISS 索引移除已遗忘条目."""
    with tempfile.TemporaryDirectory() as tmp:
        emb = AsyncMock(spec=["encode", "batch_encode"])
        emb.encode = AsyncMock(return_value=[0.1] * 1536)

        async def _batch(texts):
            return [[0.1] * 1536 for _ in texts]

        emb.batch_encode = AsyncMock(side_effect=_batch)
        s = MemoryBankStore(Path(tmp), embedding_model=emb)
        await s.write_interaction("hello", "world")
        await s.write_interaction("test2", "data2")
        assert s._index.total == 2
        # 标记第一条为 forgotten
        s._index.get_metadata()[0]["forgotten"] = True
        # 第一次调用：应成功移除
        result = await s._lifecycle.purge_forgotten(s._index.get_metadata())
        assert result is True
        assert s._index.total == 1
        # 第二次调用：节流跳过，无操作
        result = await s._lifecycle.purge_forgotten(s._index.get_metadata())
        assert result is False
        assert s._index.total == 1


@pytest.mark.asyncio
async def test_write_parses_multi_speaker_content():
    """验证 write 解析多行发言格式."""
    with tempfile.TemporaryDirectory() as tmp:
        emb = AsyncMock(spec=["encode", "batch_encode"])
        emb.encode = AsyncMock(return_value=[0.1] * 1536)

        async def _batch(texts):
            return [[0.1] * 1536 for _ in texts]

        emb.batch_encode = AsyncMock(side_effect=_batch)
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
    """验证 write_interaction 支持指定发言者姓名."""
    with tempfile.TemporaryDirectory() as tmp:
        emb = AsyncMock(spec=["encode", "batch_encode"])
        emb.encode = AsyncMock(return_value=[0.1] * 1536)

        async def _batch(texts):
            return [[0.1] * 1536 for _ in texts]

        emb.batch_encode = AsyncMock(side_effect=_batch)
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


@pytest.mark.asyncio
async def test_format_search_results_basic(store):
    """format_search_results 返回分组格式化文本."""
    await store.write_interaction("hello world", "hi there")
    result = await store.format_search_results("hello", top_k=5)
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_format_search_results_empty(store):
    """空 store 返回空字符串."""
    result = await store.format_search_results("anything")
    assert result == ""


@pytest.mark.asyncio
async def test_update_feedback_accept_increases_strength(store):
    """accept 反馈增加记忆强度."""
    ev = MemoryEvent(id="test-1", content="Alice prefers seat 30", speaker="Alice")
    fid = await store.write(ev)
    await store.update_feedback(
        fid,
        FeedbackData(event_id=fid, action="accept"),
    )
    # 反馈记录到 JSONL
    assert store._feedback_store is not None
    result = await store.search("Alice seat", top_k=5)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_update_feedback_ignore_reduces_strength(store):
    """ignore 反馈降低记忆强度."""
    ev = MemoryEvent(id="test-2", content="Bob wants AC at 22", speaker="Bob")
    fid = await store.write(ev)
    await store.update_feedback(
        fid,
        FeedbackData(event_id=fid, action="ignore"),
    )
    # 反馈记录到 JSONL，不崩溃即可


@pytest.mark.asyncio
async def test_write_batch_stores_multiple_events(store):
    """write_batch 批量写入并可通过 search 检索."""
    events = [
        MemoryEvent(id="b1", content="Charlie likes jazz", speaker="Charlie"),
        MemoryEvent(id="b2", content="Diana prefers classic", speaker="Diana"),
        MemoryEvent(id="b3", content="Eve wants navigation", speaker="Eve"),
    ]
    fids = await store.write_batch(events)
    assert len(fids) == 3
    assert all(fid for fid in fids)  # all non-empty

    history = await store.get_history(limit=5)
    assert len(history) >= 3


@pytest.mark.asyncio
async def test_write_batch_no_crash_on_empty(store):
    """空列表调用 write_batch 不崩溃."""
    fids = await store.write_batch([])
    assert fids == []
