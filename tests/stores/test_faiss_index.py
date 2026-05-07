"""FaissIndex 单元测试。"""

import tempfile
from pathlib import Path

import pytest

from app.memory.stores.memory_bank.faiss_index import FaissIndex


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
async def test_dimension_mismatch_rebuilds_index():
    """验证 add_vector 检测到维度变化时自动重建索引。"""
    with tempfile.TemporaryDirectory() as tmp:
        idx = FaissIndex(Path(tmp))
        await idx.load()
        await idx.add_vector(
            "first",
            [0.1] * 1536,
            "2024-06-15T00:00:00",
            {},
        )
        assert idx.total == 1
        await idx.add_vector(
            "second",
            [0.1] * 3072,
            "2024-06-16T00:00:00",
            {},
        )
        assert idx.total == 1  # 重建后旧条目被清除
        assert idx._dim == 3072


@pytest.mark.asyncio
async def test_update_metadata():
    """update_metadata 应更新指定条目的字段。"""
    with tempfile.TemporaryDirectory() as tmp:
        idx = FaissIndex(Path(tmp))
        await idx.load()
        fid = await idx.add_vector("test", [0.1] * 1536, "2024-06-15T00:00:00", {})
        await idx.update_metadata(fid, {"memory_strength": 5})
        assert idx.get_metadata()[0]["memory_strength"] == 5
