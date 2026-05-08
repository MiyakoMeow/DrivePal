"""FaissIndex 多用户索引单元测试。"""

import json

import faiss
import numpy as np
import pytest

from app.memory.memory_bank.faiss_index import (
    FaissIndex,
    _validate_index_count,
    _validate_metadata_structure,
)

DIM = 8


def _emb(val: float = 0.1) -> list[float]:
    return [val] * DIM


@pytest.mark.asyncio
async def test_add_and_search_single_user(tmp_path):
    """添加向量后能搜回。"""
    idx = FaissIndex(tmp_path)
    await idx.load()
    fid = await idx.add_vector("user1", "hello", _emb(), "2024-01-01T00:00:00")
    assert idx.total("user1") == 1
    results = await idx.search("user1", _emb(), top_k=5)
    assert len(results) == 1
    assert results[0]["faiss_id"] == fid
    assert results[0]["text"] == "hello"


@pytest.mark.asyncio
async def test_multi_user_isolation(tmp_path):
    """用户 A 写入不影响用户 B 搜索。"""
    idx = FaissIndex(tmp_path)
    await idx.load()
    await idx.add_vector("alice", "alice data", _emb(0.1), "2024-01-01T00:00:00")
    await idx.add_vector("bob", "bob data", _emb(0.9), "2024-01-01T00:00:00")
    assert idx.total("alice") == 1
    assert idx.total("bob") == 1

    alice_results = await idx.search("alice", _emb(0.1), top_k=5)
    assert len(alice_results) == 1
    assert alice_results[0]["text"] == "alice data"

    bob_results = await idx.search("bob", _emb(0.9), top_k=5)
    assert len(bob_results) == 1
    assert bob_results[0]["text"] == "bob data"


@pytest.mark.asyncio
async def test_add_vector_dimension_mismatch(tmp_path):
    """不同维度抛 ValueError。"""
    idx = FaissIndex(tmp_path)
    await idx.load()
    await idx.add_vector("u", "first", _emb(), "2024-01-01T00:00:00")
    with pytest.raises(ValueError, match="dimension mismatch"):
        await idx.add_vector("u", "second", [0.1] * 30, "2024-01-02T00:00:00")


@pytest.mark.asyncio
async def test_remove_vectors(tmp_path):
    """删除后搜索不返回。"""
    idx = FaissIndex(tmp_path)
    await idx.load()
    fid = await idx.add_vector("u", "to remove", _emb(), "2024-01-01T00:00:00")
    await idx.remove_vectors("u", [fid])
    assert idx.total("u") == 0
    results = await idx.search("u", _emb(), top_k=5)
    assert results == []


@pytest.mark.asyncio
async def test_save_and_reload(tmp_path):
    """持久化后重新加载，数据完整。"""
    idx = FaissIndex(tmp_path)
    await idx.load()
    fid = await idx.add_vector("u", "persist me", _emb(), "2024-01-01T00:00:00")
    await idx.save("u")

    idx2 = FaissIndex(tmp_path)
    await idx2.load()
    assert idx2.total("u") == 1
    meta = idx2.get_metadata("u")
    assert meta[0]["text"] == "persist me"
    assert meta[0]["faiss_id"] == fid


@pytest.mark.asyncio
async def test_corrupted_metadata_recovery(tmp_path):
    """metadata.json 格式错误 → 删除文件 → 返回空。"""
    idx = FaissIndex(tmp_path)
    await idx.load()
    await idx.add_vector("u", "data", _emb(), "2024-01-01T00:00:00")
    await idx.save("u")

    (tmp_path / "u" / "metadata.json").write_text("invalid json")

    idx2 = FaissIndex(tmp_path)
    await idx2.load()
    assert idx2.total("u") == 0
    assert idx2.get_metadata("u") == []


@pytest.mark.asyncio
async def test_get_all_speakers(tmp_path):
    """返回所有 speakers。"""
    idx = FaissIndex(tmp_path)
    await idx.load()
    await idx.add_vector(
        "u",
        "talk",
        _emb(),
        "2024-01-01T00:00:00",
        {"speakers": ["Gary", "AI"]},
    )
    speakers = idx.get_all_speakers("u")
    assert speakers == ["AI", "Gary"]


@pytest.mark.asyncio
async def test_get_extra_default_empty(tmp_path):
    """无 extra 文件返回空 dict。"""
    idx = FaissIndex(tmp_path)
    await idx.load()
    assert idx.get_extra("nonexistent") == {}


def test_parse_speaker_line():
    """正常解析 "Speaker: content"。"""
    spk, content = FaissIndex.parse_speaker_line("Gary: set seat to 45")
    assert spk == "Gary"
    assert content == "set seat to 45"


def test_parse_speaker_line_no_colon():
    """无冒号返回 (None, line)。"""
    spk, content = FaissIndex.parse_speaker_line("hello world")
    assert spk is None
    assert content == "hello world"


def test_parse_speaker_line_empty():
    """空字符串处理。"""
    spk, content = FaissIndex.parse_speaker_line("")
    assert spk is None
    assert content == ""


@pytest.mark.asyncio
async def test_load_empty_dir(tmp_path):
    """空目录加载后无报错。"""
    idx = FaissIndex(tmp_path)
    await idx.load()
    assert idx.total("anyone") == 0


@pytest.mark.asyncio
async def test_reload_user(tmp_path):
    """reload 重新加载指定用户。"""
    idx = FaissIndex(tmp_path)
    await idx.load()
    await idx.add_vector("u", "data", _emb(), "2024-01-01T00:00:00")
    await idx.save("u")

    (tmp_path / "u" / "metadata.json").write_text("bad")
    await idx.reload("u")
    assert idx.total("u") == 0


@pytest.mark.asyncio
async def test_get_metadata_by_id(tmp_path):
    """按 faiss_id 查找元数据。"""
    idx = FaissIndex(tmp_path)
    await idx.load()
    fid = await idx.add_vector("u", "find me", _emb(), "2024-01-01T00:00:00")
    m = idx.get_metadata_by_id("u", fid)
    assert m is not None
    assert m["text"] == "find me"
    assert idx.get_metadata_by_id("u", 999) is None


@pytest.mark.asyncio
async def test_remove_vectors_next_id_sync(tmp_path):
    """remove_vectors 后 next_id 正确同步。"""
    idx = FaissIndex(tmp_path)
    await idx.load()
    fid1 = await idx.add_vector("u", "a", _emb(0.1), "2024-01-01T00:00:00")
    fid2 = await idx.add_vector("u", "b", _emb(0.2), "2024-01-01T00:00:00")
    await idx.remove_vectors("u", [fid1])
    fid3 = await idx.add_vector("u", "c", _emb(0.3), "2024-01-01T00:00:00")
    assert fid3 == fid2 + 1


@pytest.mark.asyncio
async def test_load_with_extra_metadata(tmp_path):
    """extra_metadata.json 正常加载。"""
    idx = FaissIndex(tmp_path)
    await idx.load()
    await idx.add_vector("u", "data", _emb(), "2024-01-01T00:00:00")
    await idx.save("u")
    (tmp_path / "u" / "extra_metadata.json").write_text(
        json.dumps({"personality": "friendly"})
    )
    idx2 = FaissIndex(tmp_path)
    await idx2.load()
    assert idx2.get_extra("u") == {"personality": "friendly"}


@pytest.mark.asyncio
async def test_load_extra_null(tmp_path):
    """加载 JSON null 值 extra_metadata 回退空 dict。"""
    idx = FaissIndex(tmp_path)
    await idx.load()
    await idx.add_vector("u", "data", _emb(), "2024-01-01T00:00:00")
    await idx.save("u")
    (tmp_path / "u" / "extra_metadata.json").write_text("null")
    idx2 = FaissIndex(tmp_path)
    await idx2.load()
    assert idx2.get_extra("u") == {}


@pytest.mark.asyncio
async def test_remove_vectors_unknown_user(tmp_path):
    """移除不存在用户不报错。"""
    idx = FaissIndex(tmp_path)
    await idx.load()
    await idx.remove_vectors("ghost", [0])


@pytest.mark.asyncio
async def test_search_unknown_user(tmp_path):
    """搜索不存在用户返回空。"""
    idx = FaissIndex(tmp_path)
    await idx.load()
    results = await idx.search("ghost", _emb(), top_k=5)
    assert results == []


class TestMetadataValidation:
    """元数据校验函数测试。"""

    def test_valid_metadata(self):
        meta = [{"faiss_id": 0}, {"faiss_id": 1}, {"faiss_id": 2}]
        result = _validate_metadata_structure(meta)
        assert result == meta

    def test_invalid_root_not_list(self):
        with pytest.raises(TypeError, match="root is not list"):
            _validate_metadata_structure({"key": "value"})

    def test_invalid_entry_not_dict(self):
        with pytest.raises(ValueError, match="entry 1: invalid"):
            _validate_metadata_structure([{"faiss_id": 0}, "not a dict"])

    def test_invalid_missing_faiss_id(self):
        with pytest.raises(ValueError, match="entry 0: invalid"):
            _validate_metadata_structure([{"text": "no id"}])

    def test_invalid_faiss_id_not_int(self):
        with pytest.raises(TypeError, match="faiss_id=None.*不是整数"):
            _validate_metadata_structure([{"faiss_id": None}])

    def test_duplicate_faiss_id(self):
        with pytest.raises(ValueError, match="重复 faiss_id=1"):
            _validate_metadata_structure([{"faiss_id": 1}, {"faiss_id": 1}])

    def test_count_mismatch(self):
        idx = faiss.IndexIDMap(faiss.IndexFlatIP(4))
        vec = np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32)
        faiss.normalize_L2(vec)
        idx.add_with_ids(vec, np.array([0], dtype=np.int64))
        with pytest.raises(ValueError, match="count mismatch"):
            _validate_index_count(idx, 2)

    def test_count_match(self):
        idx = faiss.IndexIDMap(faiss.IndexFlatIP(4))
        vec = np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32)
        faiss.normalize_L2(vec)
        idx.add_with_ids(vec, np.array([0], dtype=np.int64))
        _validate_index_count(idx, 1)
