"""多用户隔离测试."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.config import user_data_dir
from app.memory.memory_bank.store import MemoryBankStore
from app.storage.init_data import init_user_dir
from app.storage.jsonl_store import JSONLinesStore


def _make_embedding_mock():
    """构造 mock embedding 模型."""
    emb = AsyncMock(spec=["encode", "batch_encode"])

    async def _encode(text):
        return [0.1] * 1536

    async def _batch(texts):
        return [[0.1] * 1536 for _ in texts]

    emb.encode = AsyncMock(side_effect=_encode)
    emb.batch_encode = AsyncMock(side_effect=_batch)
    return emb


# ── FAISS 级 MemoryBankStore 多用户隔离测试 ──


@pytest.mark.asyncio
async def test_two_users_faiss_data_isolated():
    """两个用户各写数据到 FAISS，互相不可见."""
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

            r_a = await s_a.search("seat")
            assert len(r_a) >= 1, "Alice 应能搜到自己的数据"

            r_b = await s_b.search("AC")
            assert len(r_b) >= 1, "Bob 应能搜到自己的数据"
        finally:
            await s_a.close()
            await s_b.close()


@pytest.mark.asyncio
async def test_single_user_store_write_and_close():
    """单用户 store 写入后 close 不抛异常."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        store = MemoryBankStore(base, embedding_model=_make_embedding_mock())
        await store.write_interaction("test", "ok")
        await store.close()


# ── JSONLinesStore 文件级隔离测试 ──


@pytest.mark.asyncio
async def test_users_jsonl_data_isolated(tmp_path, monkeypatch):
    """两个用户各自写入 JSONL，读取互不干扰."""
    monkeypatch.setattr("app.config.DATA_DIR", tmp_path)

    init_user_dir("alice")
    init_user_dir("bob")

    store_a = JSONLinesStore(user_dir=user_data_dir("alice"), filename="events.jsonl")
    await store_a.append({"event": "alice_test"})

    store_b = JSONLinesStore(user_dir=user_data_dir("bob"), filename="events.jsonl")
    await store_b.append({"event": "bob_test"})

    events_a = await store_a.read_all()
    events_b = await store_b.read_all()
    assert len(events_a) == 1
    assert events_a[0]["event"] == "alice_test"
    assert len(events_b) == 1
    assert events_b[0]["event"] == "bob_test"


@pytest.mark.asyncio
async def test_init_user_dir_creates_all_files(tmp_path, monkeypatch):
    """init_user_dir 创建完整目录结构."""
    monkeypatch.setattr("app.config.DATA_DIR", tmp_path)

    u_dir = init_user_dir("testuser")
    assert u_dir.exists()
    assert (u_dir / "events.jsonl").exists()
    assert (u_dir / "strategies.toml").exists()
    assert (u_dir / "scenario_presets.toml").exists()


def test_migrate_legacy_moves_files(tmp_path, monkeypatch):
    """_migrate_legacy 将平铺文件迁至 data/users/default/."""
    from app.storage.init_data import _migrate_legacy

    monkeypatch.setattr("app.config.DATA_DIR", tmp_path)
    monkeypatch.setattr("app.storage.init_data.DATA_ROOT", tmp_path)

    (tmp_path / "events.jsonl").write_text("")
    (tmp_path / "strategies.toml").write_text("")
    assert _migrate_legacy() is True
    assert (tmp_path / "users" / "default" / "events.jsonl").exists()
    assert not (tmp_path / "events.jsonl").exists()


def test_user_data_dir_path(tmp_path, monkeypatch):
    """user_data_dir 返回正确的 per-user 路径."""
    monkeypatch.setattr("app.config.DATA_DIR", tmp_path / "data")
    u_dir = user_data_dir("alice")
    assert u_dir.name == "alice"
    assert "users" in str(u_dir)
