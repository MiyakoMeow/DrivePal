"""FaissIndexManager 单元测试（多用户版）。"""

from pathlib import Path

import pytest

from app.memory.memory_bank.faiss_index import (
    FaissIndexManager,
    _validate_index_count,
    _validate_metadata_structure,
)


@pytest.fixture
def manager(tmp_path: Path) -> FaissIndexManager:
    return FaissIndexManager(tmp_path)


@pytest.mark.asyncio
async def test_add_and_search(manager: FaissIndexManager) -> None:
    """添加向量后应能检索到。"""
    uid = "user_1"
    emb = [0.1] * 1536
    fid = await manager.add_vector(uid, "hello world", emb, "2026-01-01T00:00:00")
    assert fid == 0
    total = await manager.total(uid)
    assert total == 1

    results = await manager.search(uid, emb, top_k=5)
    assert len(results) == 1
    assert results[0]["text"] == "hello world"
    assert results[0]["_meta_idx"] == 0


@pytest.mark.asyncio
async def test_metadata_deep_copy(manager: FaissIndexManager) -> None:
    """get_metadata 返回 deep copy，修改副本不影响内部。"""
    uid = "user_1"
    emb = [0.1] * 1536
    await manager.add_vector(uid, "test", emb, "2026-01-01T00:00:00")
    meta = manager.get_metadata(uid)
    meta[0]["text"] = "MUTATED"
    assert manager.get_metadata(uid)[0]["text"] == "test"


@pytest.mark.asyncio
async def test_multi_user_isolation(manager: FaissIndexManager) -> None:
    """多用户隔离：user_a 的写入不影响 user_b。"""
    emb = [0.1] * 1536
    await manager.add_vector("user_a", "text_a", emb, "2026-01-01T00:00:00")
    await manager.add_vector("user_b", "text_b", emb, "2026-01-01T00:00:00")
    total_a = await manager.total("user_a")
    total_b = await manager.total("user_b")
    assert total_a == 1
    assert total_b == 1
    assert manager.get_metadata("user_a")[0]["text"] == "text_a"


@pytest.mark.asyncio
async def test_persistence_roundtrip(manager: FaissIndexManager, tmp_path: Path) -> None:
    """保存后重新加载应保持数据。"""
    uid = "user_1"
    emb = [0.1] * 1536
    await manager.add_vector(uid, "persist me", emb, "2026-01-01T00:00:00")
    await manager.save(uid)

    manager2 = FaissIndexManager(tmp_path)
    await manager2.load(uid)
    total = await manager2.total(uid)
    assert total == 1
    assert manager2.get_metadata(uid)[0]["text"] == "persist me"


@pytest.mark.asyncio
async def test_corrupted_metadata_rebuilds(tmp_path: Path) -> None:
    """损坏的 metadata.json 导致空索引重建而非崩溃。"""
    uid = "user_1"
    user_dir = tmp_path / f"user_{uid}"
    user_dir.mkdir(parents=True)
    (user_dir / "metadata.json").write_text("NOT JSON")
    (user_dir / "index.faiss").write_bytes(b"")

    manager = FaissIndexManager(tmp_path)
    await manager.load(uid)
    total = await manager.total(uid)
    assert total == 0


@pytest.mark.asyncio
async def test_update_metadata(manager: FaissIndexManager) -> None:
    """update_metadata 显式更新单条。"""
    uid = "user_1"
    emb = [0.1] * 1536
    fid = await manager.add_vector(uid, "test", emb, "2026-01-01T00:00:00")
    await manager.update_metadata(uid, fid, {"memory_strength": 5})
    assert manager.get_metadata(uid)[0]["memory_strength"] == 5


@pytest.mark.asyncio
async def test_batch_update_metadata(manager: FaissIndexManager) -> None:
    """batch_update_metadata 批量更新。"""
    uid = "user_1"
    emb = [0.1] * 1536
    fid1 = await manager.add_vector(uid, "a", emb, "2026-01-01T00:00:00")
    fid2 = await manager.add_vector(uid, "b", emb, "2026-01-02T00:00:00")
    await manager.batch_update_metadata(
        uid, {0: {"memory_strength": 3}, 1: {"memory_strength": 7}}
    )
    updated = manager.get_metadata(uid)
    assert updated[0]["memory_strength"] == 3
    assert updated[1]["memory_strength"] == 7


@pytest.mark.asyncio
async def test_remove_vectors_syncs_state(manager: FaissIndexManager) -> None:
    """remove_vectors 后 total 减少，next_id 正确。"""
    uid = "user_1"
    emb = [0.1] * 1536
    fid1 = await manager.add_vector(uid, "a", emb, "2026-01-01T00:00:00")
    fid2 = await manager.add_vector(uid, "b", emb, "2026-01-02T00:00:00")
    total_before = await manager.total(uid)
    assert total_before == 2
    await manager.remove_vectors(uid, [fid1])
    total_after = await manager.total(uid)
    assert total_after == 1
    # next_id 不应受删除影响（单调递增）
    emb2 = [0.2] * 1536
    fid3 = await manager.add_vector(uid, "c", emb2, "2026-01-03T00:00:00")
    assert fid3 == fid2 + 1  # 单调递增，不复用


@pytest.mark.asyncio
async def test_extra_persistence(manager: FaissIndexManager, tmp_path: Path) -> None:
    """get_extra 及持久化。"""
    uid = "user_1"
    emb = [0.1] * 1536
    await manager.add_vector(uid, "test", emb, "2026-01-01T00:00:00")
    extra = manager.get_extra(uid)
    extra["overall_summary"] = "test summary"
    await manager.save(uid)

    manager2 = FaissIndexManager(tmp_path)
    await manager2.load(uid)
    assert manager2.get_extra(uid).get("overall_summary") == "test summary"


@pytest.mark.asyncio
async def test_load_creates_user_dir_on_demand(manager: FaissIndexManager) -> None:
    """不存在的 user_id 应创建空索引。"""
    uid = "new_user"
    await manager.add_vector(uid, "first", [0.1] * 1536, "2026-01-01T00:00:00")
    total = await manager.total(uid)
    assert total == 1


@pytest.mark.asyncio
async def test_get_metadata_by_id(manager: FaissIndexManager) -> None:
    """get_metadata_by_id 返回正确结果。"""
    uid = "user_1"
    emb = [0.1] * 1536
    fid = await manager.add_vector(uid, "target", emb, "2026-01-01T00:00:00")
    m = manager.get_metadata_by_id(uid, fid)
    assert m is not None
    assert m["text"] == "target"


@pytest.mark.asyncio
async def test_get_all_speakers(manager: FaissIndexManager) -> None:
    """get_all_speakers 返回已知说话人。"""
    uid = "user_1"
    emb = [0.1] * 1536
    await manager.add_vector(
        uid, "hello", emb, "2026-01-01T00:00:00", {"speakers": ["Alice", "Bob"]}
    )
    speakers = manager.get_all_speakers(uid)
    assert "Alice" in speakers
    assert "Bob" in speakers


def test_parse_speaker_line() -> None:
    """parse_speaker_line 静态方法正常。"""
    spk, content = FaissIndexManager.parse_speaker_line("Gary: set seat to 45")
    assert spk == "Gary"
    assert content == "set seat to 45"

    spk, content = FaissIndexManager.parse_speaker_line("no colon")
    assert spk is None
    assert content == "no colon"

    spk, content = FaissIndexManager.parse_speaker_line("")
    assert spk is None
    assert content == ""
