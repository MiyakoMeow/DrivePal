"""六阶段检索管道单元测试——mock FaissIndex + EmbeddingClient。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.memory.memory_bank.config import MemoryBankConfig
from app.memory.memory_bank.observability import MemoryBankMetrics
from app.memory.memory_bank.retrieval import RetrievalPipeline


@pytest.fixture
def mock_index():
    idx = MagicMock()
    idx.total = 0
    idx.get_metadata = MagicMock(return_value=[])
    idx.search = AsyncMock(return_value=[])
    return idx


@pytest.fixture
def mock_embedding():
    emb = AsyncMock()
    emb.encode = AsyncMock(return_value=[0.1] * 1536)
    return emb


@pytest.fixture
def pipeline(mock_index, mock_embedding):
    return RetrievalPipeline(mock_index, mock_embedding, MemoryBankConfig())


@pytest.mark.asyncio
async def test_empty_index_returns_empty(pipeline, mock_index):
    """total==0 时返回空列表。"""
    mock_index.total = 0
    results, updated = await pipeline.search("query")
    assert results == []
    assert not updated


@pytest.mark.asyncio
async def test_top_k_zero_returns_empty(pipeline):
    """top_k<=0 直接返回空。"""
    results, updated = await pipeline.search("query", top_k=0)
    assert results == []
    assert not updated


@pytest.mark.asyncio
async def test_single_result_no_neighbors(pipeline, mock_index, mock_embedding):
    """单条命中无邻居 → 1 条结果。"""
    mock_index.total = 5
    mock_index.get_metadata.return_value = [
        {
            "faiss_id": 0,
            "text": "test entry",
            "source": "2024-06-15",
            "speakers": ["Gary"],
            "memory_strength": 1,
            "forgotten": False,
        }
    ]
    mock_index.search = AsyncMock(
        return_value=[
            {
                "faiss_id": 0,
                "text": "test entry",
                "source": "2024-06-15",
                "score": 0.9,
                "_meta_idx": 0,
                "speakers": ["Gary"],
                "memory_strength": 1,
                "forgotten": False,
            }
        ]
    )
    results, updated = await pipeline.search("query")
    assert len(results) >= 1
    assert results[0].get("text", "")


@pytest.mark.asyncio
async def test_merge_neighbors_same_source(pipeline, mock_index, mock_embedding):
    """同 source 连续 3 条，命中中间 → 合并为 1 条。"""
    meta = []
    for i in range(3):
        meta.append(
            {
                "faiss_id": i,
                "text": f"entry {i}",
                "source": "2024-06-15",
                "speakers": ["Gary"],
                "memory_strength": 1,
                "forgotten": False,
            }
        )
    mock_index.total = 3
    mock_index.get_metadata.return_value = meta
    mock_index.search = AsyncMock(
        return_value=[
            {
                "faiss_id": 1,
                "text": "entry 1",
                "source": "2024-06-15",
                "score": 0.8,
                "_meta_idx": 1,
                "speakers": ["Gary"],
                "memory_strength": 1,
                "forgotten": False,
            }
        ]
    )
    results, updated = await pipeline.search("query")
    assert len(results) >= 1
    # 验证邻接条目正确合并：键值分割符剥离后相邻文本以分号连接
    assert "; " in results[0].get("text", "")


@pytest.mark.asyncio
async def test_speaker_filter_downweights_positive(
    pipeline, mock_index, mock_embedding
):
    """query 提及 Alice，结果 speakers=["Bob"] → 其他结果含 Alice 激活过滤器 → Bob 被降权。"""
    meta = [
        {
            "faiss_id": 0,
            "text": "Alice's preference",
            "source": "day1",
            "speakers": ["Alice"],
            "memory_strength": 1,
            "forgotten": False,
        },
        {
            "faiss_id": 1,
            "text": "Bob's preference",
            "source": "day2",
            "speakers": ["Bob"],
            "memory_strength": 1,
            "forgotten": False,
        },
    ]
    mock_index.total = 2
    mock_index.get_metadata.return_value = meta
    mock_index.search = AsyncMock(
        return_value=[
            {
                "faiss_id": 0,
                "text": "Alice's preference",
                "source": "day1",
                "score": 0.9,
                "_meta_idx": 0,
                "speakers": ["Alice"],
                "memory_strength": 1,
                "forgotten": False,
            },
            {
                "faiss_id": 1,
                "text": "Bob's preference",
                "source": "day2",
                "score": 1.0,
                "_meta_idx": 1,
                "speakers": ["Bob"],
                "memory_strength": 1,
                "forgotten": False,
            },
        ]
    )
    results, updated = await pipeline.search("Alice's setting")
    assert len(results) >= 2
    # Bob 的 score 应被降权，低于 Alice
    alice_result = next((r for r in results if "Alice" in r.get("text", "")), None)
    bob_result = next((r for r in results if "Bob" in r.get("text", "")), None)
    assert alice_result is not None
    assert bob_result is not None
    assert bob_result.get("score", 0.0) < alice_result.get("score", 0.0)


@pytest.mark.asyncio
async def test_updated_flag_on_memory_strength_change(
    pipeline, mock_index, mock_embedding
):
    """检索命中应触发 memory_strength 更新 → updated=True。"""
    meta = [
        {
            "faiss_id": 0,
            "text": "test",
            "source": "2024-06-15",
            "speakers": ["Gary"],
            "memory_strength": 1,
            "forgotten": False,
        }
    ]
    mock_index.total = 1
    mock_index.get_metadata.return_value = meta
    mock_index.search = AsyncMock(
        return_value=[
            {
                "faiss_id": 0,
                "text": "test",
                "source": "2024-06-15",
                "score": 0.5,
                "_meta_idx": 0,
                "speakers": ["Gary"],
                "memory_strength": 1,
                "forgotten": False,
            }
        ]
    )
    results, updated = await pipeline.search("query")
    assert updated
    assert meta[0]["memory_strength"] == 2


@pytest.mark.asyncio
async def test_strength_capped_at_max(mock_index, mock_embedding):
    """memory_strength 不超过 max_memory_strength。"""
    config = MemoryBankConfig(max_memory_strength=5)
    pipeline = RetrievalPipeline(mock_index, mock_embedding, config)
    mock_index.total = 10
    metadata = [
        {
            "faiss_id": 0,
            "text": "t",
            "source": "d",
            "speakers": ["A"],
            "memory_strength": 5,
            "forgotten": False,
        }
    ]
    mock_index.get_metadata.return_value = metadata
    mock_index.search = AsyncMock(
        return_value=[
            {
                "faiss_id": 0,
                "text": "t",
                "source": "d",
                "score": 0.9,
                "_meta_idx": 0,
                "speakers": ["A"],
                "forgotten": False,
            }
        ]
    )
    _, updated = await pipeline.search("query")
    assert metadata[0]["memory_strength"] == 5  # 已达上限，不增长


@pytest.mark.asyncio
async def test_retention_weighting_reranks(mock_index, mock_embedding):
    """保留率加权后新鲜条目排到前面。"""
    config = MemoryBankConfig(retrieval_alpha=0.7)
    pipeline = RetrievalPipeline(mock_index, mock_embedding, config)
    mock_index.total = 10
    metadata = [
        {
            "faiss_id": 0,
            "text": "new",
            "source": "d1",
            "speakers": ["A"],
            "memory_strength": 5,
            "last_recall_date": "2026-05-10",
            "forgotten": False,
        },
        {
            "faiss_id": 1,
            "text": "old",
            "source": "d2",
            "speakers": ["A"],
            "memory_strength": 1,
            "last_recall_date": "2020-01-01",
            "forgotten": False,
        },
    ]
    mock_index.get_metadata.return_value = metadata
    mock_index.search = AsyncMock(
        return_value=[
            {
                "faiss_id": 0,
                "text": "new",
                "source": "d1",
                "score": 0.8,
                "_meta_idx": 0,
                "speakers": ["A"],
                "forgotten": False,
            },
            {
                "faiss_id": 1,
                "text": "old",
                "source": "d2",
                "score": 0.85,
                "_meta_idx": 1,
                "speakers": ["A"],
                "forgotten": False,
            },
        ]
    )
    results, _ = await pipeline.search("query", top_k=2, reference_date="2026-05-10")
    assert len(results) >= 2
    # 新鲜条目加权后排第一
    assert results[0].get("text", "") == "new"


@pytest.mark.asyncio
async def test_bm25_fallback_triggered_on_low_faiss_score(mock_index, mock_embedding):
    """FAISS 最高分 < bm25_fallback_threshold 时触发 BM25 回退"""
    config = MemoryBankConfig(bm25_fallback_enabled=True, bm25_fallback_threshold=0.5)
    pipeline = RetrievalPipeline(mock_index, mock_embedding, config)
    mock_index.total = 10
    mock_index.get_metadata.return_value = [
        {
            "faiss_id": 0,
            "text": "test entry one two three",
            "source": "d1",
            "speakers": ["A"],
            "memory_strength": 1,
            "forgotten": False,
            "last_recall_date": "2026-05-10",
        },
    ]
    mock_index.search = AsyncMock(
        return_value=[
            {
                "faiss_id": 0,
                "text": "t",
                "source": "d1",
                "score": 0.3,
                "_meta_idx": 0,
                "speakers": ["A"],
                "forgotten": False,
            }
        ]
    )
    results, _ = await pipeline.search("test query", top_k=2)
    assert len(results) >= 1


def test_merge_dropped_tracks_count():
    """合并丢弃时 metrics.forget_count 应递增。"""
    from app.memory.memory_bank.retrieval import (
        _build_overlap_groups,
        _merge_overlapping_results,
    )

    metrics = MemoryBankMetrics()
    merging = [
        {
            "_merged_indices": [0, 1],
            "text": "part0\x00part1",
            "score": 0.5,
            "memory_strength": 1,
        },
        {
            "_merged_indices": [1, 2],
            "text": "part1\x00part2",
            "score": 0.4,
            "memory_strength": 1,
        },
    ]
    groups = _build_overlap_groups(merging)
    assert len(groups) >= 1

    result = _merge_overlapping_results(merging, metrics=metrics)
    assert len(result) > 0
    assert metrics.forget_count == 0

    # 所有成员空文本或 text/indices 长度不匹配 → 全部丢弃
    merging_all_empty = [
        {"_merged_indices": [0, 1], "text": "", "score": 0.5, "memory_strength": 1},
        {"_merged_indices": [1, 2], "text": "", "score": 0.4, "memory_strength": 1},
    ]
    _merge_overlapping_results(merging_all_empty, metrics=metrics)
    # 两组重叠，合并为一组后丢弃
    assert metrics.forget_count > 0
