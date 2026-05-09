"""多用户隔离测试。"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.memory.memory_bank.store import MemoryBankStore


def _make_embedding_mock():
    emb = AsyncMock(spec=["encode", "batch_encode"])
    emb.encode = AsyncMock(return_value=[0.1] * 1536)

    async def _batch(texts):
        return [[0.1] * 1536 for _ in texts]

    emb.batch_encode = AsyncMock(side_effect=_batch)
    return emb


@pytest.mark.asyncio
async def test_two_users_data_isolated():
    """两个用户各写数据，互相不可见。"""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)

        s_a = MemoryBankStore(
            base, embedding_model=_make_embedding_mock(), user_id="alice"
        )
        s_b = MemoryBankStore(
            base, embedding_model=_make_embedding_mock(), user_id="bob"
        )

        try:
            await s_a.write_interaction("alice's preference: seat 30", "noted")
            await s_b.write_interaction("bob's preference: AC 22", "noted")

            # Alice 搜自己的数据
            r_a = await s_a.search("seat")
            assert len(r_a) >= 1
            assert any("alice" in r.event.get("content", "").lower() for r in r_a)

            # Bob 搜自己的数据
            r_b = await s_b.search("AC")
            assert len(r_b) >= 1

            # Alice 不应看到 Bob 的数据
            r_a_bob = await s_a.search("AC")
            for r in r_a_bob:
                content = r.event.get("content", "")
                assert "bob" not in content.lower()
        finally:
            await s_a.close()
            await s_b.close()


@pytest.mark.asyncio
async def test_store_close_persists_then_shuts_down():
    """close() 关闭后台任务。"""
    with tempfile.TemporaryDirectory() as tmp:
        s = MemoryBankStore(Path(tmp), embedding_model=_make_embedding_mock())
        await s.write_interaction("test", "ok")
        await s.close()
        # close 不应抛异常，且后台任务已清理
        assert s._bg.pending_count == 0


@pytest.mark.asyncio
async def test_single_user_store_write_and_close():
    """单用户 store 写入后正确关闭。"""
    with tempfile.TemporaryDirectory() as tmp:
        s1 = MemoryBankStore(
            Path(tmp), embedding_model=_make_embedding_mock(), user_id="same"
        )
        await s1.write_interaction("x", "y")
        assert s1._index.total == 1
        await s1.close()
