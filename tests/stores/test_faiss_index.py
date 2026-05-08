"""FaissIndex 单元测试。"""

import tempfile
from pathlib import Path

import faiss
import numpy as np
import pytest

from app.memory.memory_bank.index import (
    FaissIndex,
    _validate_index_count,
    _validate_metadata_structure,
)


@pytest.mark.asyncio
async def test_load_creates_new_index_when_no_files():
    """无文件时 load 应创建空索引。"""
    with tempfile.TemporaryDirectory() as tmp:
        idx = FaissIndex(Path(tmp))
        await idx.load()
        assert idx.total == 0
        assert idx.get_metadata() == []


@pytest.mark.asyncio
async def test_add_vector_and_search():
    """添加向量后应能检索到。"""
    with tempfile.TemporaryDirectory() as tmp:
        idx = FaissIndex(Path(tmp))
        await idx.load()
        emb = [0.1] * 1536
        fid = await idx.add_vector(
            "test text", emb, "2024-06-15T00:00:00", {"source": "2024-06-15"}
        )
        assert isinstance(fid, int)
        assert idx.total == 1
        results = await idx.search([0.1] * 1536, top_k=5)
        assert len(results) == 1
        assert results[0]["faiss_id"] == fid


@pytest.mark.asyncio
async def test_save_and_load_persistence():
    """保存后重新加载应保持数据。"""
    with tempfile.TemporaryDirectory() as tmp:
        idx = FaissIndex(Path(tmp))
        await idx.load()
        await idx.add_vector("hello", [0.2] * 1536, "2024-06-15T00:00:00", {})
        await idx.save()

        idx2 = FaissIndex(Path(tmp))
        await idx2.load()
        assert idx2.total == 1
        assert idx2.get_metadata()[0]["text"] == "hello"


@pytest.mark.asyncio
async def test_corrupted_metadata_rebuilds():
    """损坏的元数据应触发重建空索引。"""
    with tempfile.TemporaryDirectory() as tmp:
        idx = FaissIndex(Path(tmp))
        await idx.load()
        await idx.add_vector("x", [0.3] * 1536, "2024-06-15T00:00:00", {})
        await idx.save()
        Path(tmp, "metadata.json").write_text("invalid json")
        idx2 = FaissIndex(Path(tmp))
        await idx2.load()
        assert idx2.total == 0


@pytest.mark.asyncio
async def test_dimension_mismatch_raises():
    """维度不匹配时抛出 ValueError 而非静默重建。"""
    with tempfile.TemporaryDirectory() as tmp:
        idx = FaissIndex(Path(tmp))
        await idx.load()
        await idx.add_vector("first", [0.1] * 1536, "2024-06-15T00:00:00", {})
        assert idx.total == 1
        with pytest.raises(ValueError, match="dimension mismatch"):
            await idx.add_vector("second", [0.1] * 3072, "2024-06-16T00:00:00", {})


@pytest.mark.asyncio
async def test_update_metadata():
    """update_metadata 应更新指定条目的字段。"""
    with tempfile.TemporaryDirectory() as tmp:
        idx = FaissIndex(Path(tmp))
        await idx.load()
        fid = await idx.add_vector("test", [0.1] * 1536, "2024-06-15T00:00:00", {})
        await idx.update_metadata(fid, {"memory_strength": 5})
        assert idx.get_metadata()[0]["memory_strength"] == 5


def test_parse_speaker_line_valid():
    """验证有效说话人行解析。"""
    speaker, content = FaissIndex.parse_speaker_line("Gary: set seat to 45")
    assert speaker == "Gary"
    assert content == "set seat to 45"


def test_parse_speaker_line_no_colon():
    """验证无冒号格式返回 speaker=None。"""
    speaker, content = FaissIndex.parse_speaker_line("hello world")
    assert speaker is None
    assert content == "hello world"


def test_parse_speaker_line_empty():
    """验证空字符串处理。"""
    speaker, content = FaissIndex.parse_speaker_line("")
    assert speaker is None
    assert content == ""


@pytest.mark.asyncio
async def test_add_vector_updates_speakers_cache():
    """验证 add_vector 中 speakers 参数更新缓存。"""
    with tempfile.TemporaryDirectory() as tmp:
        idx = FaissIndex(Path(tmp))
        await idx.load()
        await idx.add_vector(
            "test",
            [0.1] * 1536,
            "2024-06-15T00:00:00",
            {"speakers": ["Gary", "AI"]},
        )
        assert "Gary" in idx.get_all_speakers()


class TestMetadataValidation:
    """元数据校验函数测试。"""

    def test_valid_metadata(self):
        """有效的 metadata list 应通过校验。"""
        meta = [{"faiss_id": 0}, {"faiss_id": 1}, {"faiss_id": 2}]
        result = _validate_metadata_structure(meta)
        assert result == meta

    def test_invalid_root_not_list(self):
        """根元素不是 list 时应抛出 TypeError。"""
        with pytest.raises(TypeError, match="root is not list"):
            _validate_metadata_structure({"key": "value"})

    def test_invalid_entry_not_dict(self):
        """条目不是 dict 时应抛出 ValueError。"""
        with pytest.raises(ValueError, match="entry 1: invalid"):
            _validate_metadata_structure([{"faiss_id": 0}, "not a dict"])

    def test_invalid_missing_faiss_id(self):
        """缺少 faiss_id 的条目应抛出 ValueError。"""
        with pytest.raises(ValueError, match="entry 0: invalid"):
            _validate_metadata_structure([{"text": "no id"}])

    def test_invalid_faiss_id_not_int(self):
        """faiss_id 不是 int 时应抛出 TypeError。"""
        with pytest.raises(TypeError, match="faiss_id=None.*不是整数"):
            _validate_metadata_structure([{"faiss_id": None}])

    def test_duplicate_faiss_id(self):
        """重复 faiss_id 时应抛出 ValueError。"""
        with pytest.raises(ValueError, match="重复 faiss_id=1"):
            _validate_metadata_structure([{"faiss_id": 1}, {"faiss_id": 1}])

    def test_count_mismatch(self):
        """索引条目数与 metadata 数不一致应抛出 ValueError。"""
        idx = faiss.IndexIDMap(faiss.IndexFlatIP(4))
        vec = np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32)
        faiss.normalize_L2(vec)
        idx.add_with_ids(vec, np.array([0], dtype=np.int64))
        with pytest.raises(ValueError, match="count mismatch"):
            _validate_index_count(idx, 2)

    def test_count_match(self):
        """索引条目与 metadata 数一致应通过。"""
        idx = faiss.IndexIDMap(faiss.IndexFlatIP(4))
        vec = np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32)
        faiss.normalize_L2(vec)
        idx.add_with_ids(vec, np.array([0], dtype=np.int64))
        _validate_index_count(idx, 1)


async def test_remove_vectors_syncs_next_id(tmp_path: Path) -> None:
    """remove_vectors 后 _next_id 正确同步。"""
    idx = FaissIndex(tmp_path)
    fid1 = await idx.add_vector("a", [0.1, 0.2, 0.3], "2024-01-01T00:00:00")
    fid2 = await idx.add_vector("b", [0.4, 0.5, 0.6], "2024-01-01T00:00:00")
    assert idx.next_id == fid2 + 1
    await idx.remove_vectors([fid1])
    assert idx.next_id == fid2 + 1


async def test_add_vector_dim_mismatch_raises(tmp_path: Path) -> None:
    """维度不匹配时抛出 ValueError 而非静默重建。"""
    idx = FaissIndex(tmp_path)
    await idx.add_vector("a", [0.1, 0.2, 0.3], "2024-01-01T00:00:00")
    with pytest.raises(ValueError, match="dimension mismatch"):
        await idx.add_vector("b", [0.4, 0.5], "2024-01-01T00:00:00")


async def test_get_extra_null_defense(tmp_path: Path) -> None:
    """get_extra 返回空 dict 而非 None。"""
    idx = FaissIndex(tmp_path)
    idx._extra = {"key": "val"}
    assert idx.get_extra() == {"key": "val"}
    idx._extra = None
    assert idx.get_extra() == {}


async def test_load_extra_null_defense(tmp_path: Path) -> None:
    """加载 JSON null 值的 extra_metadata.json 时回退空 dict。"""
    idx = FaissIndex(tmp_path)
    await idx.add_vector("a", [0.1, 0.2, 0.3], "2024-01-01T00:00:00")
    await idx.save()
    (tmp_path / "extra_metadata.json").write_text("null")
    idx2 = FaissIndex(tmp_path)
    await idx2.load()
    assert idx2.get_extra() == {}


async def test_load_extra_malformed_json(tmp_path: Path) -> None:
    """加载语法错误的 extra_metadata.json 时回退空 dict，主索引不受影响。"""
    idx = FaissIndex(tmp_path)
    await idx.add_vector("a", [0.1, 0.2, 0.3], "2024-01-01T00:00:00")
    await idx.save()
    (tmp_path / "extra_metadata.json").write_text("{")
    idx2 = FaissIndex(tmp_path)
    await idx2.load()
    assert idx2.get_extra() == {}
    assert idx2.total == 1
