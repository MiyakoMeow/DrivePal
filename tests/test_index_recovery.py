"""FaissIndex 降级恢复测试。"""

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from app.memory.memory_bank.index import FaissIndex


@pytest.mark.asyncio
async def test_corrupted_metadata_rebuilds_skeleton_from_index():
    """metadata.json 格式错但 index.faiss 正常 → 重建骨架，保留向量。"""
    with tempfile.TemporaryDirectory() as tmp:
        idx = FaissIndex(Path(tmp))
        await idx.load()
        await idx.add_vector("hello", [0.3] * 1536, "2024-06-15T00:00:00", {})
        await idx.save()
        # 破坏 metadata
        Path(tmp, "metadata.json").write_text("garbage")
        idx2 = FaissIndex(Path(tmp))
        result = await idx2.load()
        assert result.ok
        assert len(result.warnings) >= 1
        assert idx2.total == 1
        meta = idx2.get_metadata()
        assert len(meta) == 1
        assert meta[0].get("corrupted") is True
        assert meta[0]["text"] == ""


@pytest.mark.asyncio
async def test_corrupted_index_backed_up_and_rebuilt():
    """index.faiss 损坏 → 备份 .bak，重建空索引。"""
    with tempfile.TemporaryDirectory() as tmp:
        idx = FaissIndex(Path(tmp))
        await idx.load()
        await idx.add_vector("x", [0.3] * 1536, "2024-06-15T00:00:00", {})
        await idx.save()
        # 破坏 index
        Path(tmp, "index.faiss").write_bytes(b"corrupted")
        idx2 = FaissIndex(Path(tmp))
        result = await idx2.load()
        assert not result.ok
        assert idx2.total == 0
        bak = Path(tmp, "index.faiss.bak")
        assert bak.exists()


@pytest.mark.asyncio
async def test_count_mismatch_adds_skeleton_entries():
    """metadata 比 index 少条目 → 自动补齐骨架 entry。"""
    with tempfile.TemporaryDirectory() as tmp:
        idx = FaissIndex(Path(tmp))
        await idx.load()
        await idx.add_vector("a", [0.1] * 1536, "2024-01-01T00:00:00", {})
        await idx.add_vector("b", [0.2] * 1536, "2024-01-02T00:00:00", {})
        await idx.save()
        # 删掉 metadata 中第一条
        meta = json.loads(Path(tmp, "metadata.json").read_text())
        meta.pop(0)
        Path(tmp, "metadata.json").write_text(json.dumps(meta))
        # 加载
        idx2 = FaissIndex(Path(tmp))
        result = await idx2.load()
        assert idx2.total == 2
        assert result.warnings
        # skeleton entry 含 corrupted 标记和空 text
        meta2 = idx2.get_metadata()
        assert any(m.get("corrupted") for m in meta2)
        assert any(m.get("text") == "" for m in meta2)


@pytest.mark.asyncio
async def test_compute_reference_date_from_metadata():
    """compute_reference_date 从 metadata 找最大时间戳 + offset。"""
    with tempfile.TemporaryDirectory() as tmp:
        idx = FaissIndex(Path(tmp))
        await idx.load()
        await idx.add_vector("a", [0.1] * 1536, "2024-06-10T00:00:00", {})
        await idx.add_vector("b", [0.2] * 1536, "2024-06-15T00:00:00", {})
        ref = idx.compute_reference_date(offset_days=1)
        assert ref == "2024-06-16"
        ref2 = idx.compute_reference_date(offset_days=0)
        assert ref2 == "2024-06-15"


@pytest.mark.asyncio
async def test_compute_reference_date_empty():
    """空 metadata 返回 UTC 当天。"""
    with tempfile.TemporaryDirectory() as tmp:
        idx = FaissIndex(Path(tmp))
        await idx.load()
        ref = idx.compute_reference_date()
        assert ref  # 任意非空字符串


@pytest.mark.asyncio
async def test_load_does_not_block_event_loop():
    """load() 不阻塞事件循环——call_soon 回调查看 yield 点。"""
    loop_interleaved = False

    def mark_interleaved():
        nonlocal loop_interleaved
        loop_interleaved = True

    with tempfile.TemporaryDirectory() as tmp:
        idx = FaissIndex(Path(tmp))
        await idx.load()
        await idx.add_vector("x", [0.1] * 1536, "2024-06-15T00:00:00", {})
        await idx.save()

        idx2 = FaissIndex(Path(tmp))
        loop = asyncio.get_running_loop()
        loop.call_soon(mark_interleaved)
        await idx2.load()
        assert loop_interleaved, "事件循环被阻塞——load() 未让出控制权"
