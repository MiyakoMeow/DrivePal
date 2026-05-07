"""RetrievalPipeline 单元测试。"""

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.memory.memory_bank.faiss_index import FaissIndex
from app.memory.memory_bank.retrieval import (
    DEFAULT_CHUNK_SIZE,
    RetrievalPipeline,
    _clean_search_result,
    _get_effective_chunk_size,
    _merge_overlapping_results,
    _strip_source_prefix,
    _update_memory_strengths,
    _word_in_text,
)


@pytest.fixture
def mock_embedding():
    """Mock EmbeddingModel fixture。"""
    m = AsyncMock()
    m.encode.return_value = [0.1] * 1536
    return m


@pytest.mark.asyncio
async def test_search_empty_index_returns_empty_list(mock_embedding):
    """空索引时 search 应返回空列表。"""
    with tempfile.TemporaryDirectory() as tmp:
        idx = FaissIndex(Path(tmp))
        await idx.load()
        pipe = RetrievalPipeline(idx, mock_embedding)
        results = await pipe.search("anything")
        assert results == []


@pytest.mark.asyncio
async def test_search_returns_results(mock_embedding):
    """有数据时 search 应返回结果。"""
    with tempfile.TemporaryDirectory() as tmp:
        idx = FaissIndex(Path(tmp))
        await idx.load()
        emb = [0.1] * 1536
        for _, text in enumerate(["Gary likes seat 45", "Patricia wants AC at 22"]):
            await idx.add_vector(
                text,
                emb,
                "2024-06-15T10:00:00",
                {"source": "2024-06-15", "speakers": [text.split()[0]]},
            )
        pipe = RetrievalPipeline(idx, mock_embedding)
        results = await pipe.search("Gary seat")
        assert len(results) >= 1


def test_merge_overlapping_dedup():
    """并查集重叠消除。"""
    results = [
        {
            "_merged_indices": [0, 1, 2],
            "score": 0.9,
            "text": "a\x00b\x00c",
            "speakers": [],
            "memory_strength": 2,
        },
        {
            "_merged_indices": [2, 3, 4],
            "score": 0.8,
            "text": "c\x00d\x00e",
            "speakers": [],
            "memory_strength": 1,
        },
    ]
    merged = _merge_overlapping_results(results)
    assert len(merged) == 1
    assert merged[0]["_merged_indices"] == [0, 1, 2, 3, 4]


def test_merge_overlapping_non_overlapping_passthrough():
    """无重叠结果应透传。"""
    results = [
        {
            "_merged_indices": [0, 1],
            "score": 0.9,
            "text": "a\x00b",
            "speakers": [],
            "memory_strength": 2,
        },
        {
            "_merged_indices": [3, 4],
            "score": 0.8,
            "text": "d\x00e",
            "speakers": [],
            "memory_strength": 1,
        },
    ]
    merged = _merge_overlapping_results(results)
    assert len(merged) == 2


def test_merge_overlapping_no_merge_items_untouched():
    """无合并项的输入应原样返回。"""
    results = [
        {"score": 0.9, "text": "hello", "speakers": []},
        {"_merged_indices": [0], "score": 0.8, "text": "world", "speakers": []},
    ]
    merged = _merge_overlapping_results(results)
    assert len(merged) == 2


def test_strip_source_prefix_removes_english_prefix():
    """应去除英文前缀标记。"""
    assert (
        _strip_source_prefix(
            "Conversation content on 2024-06-15:Hello world", "2024-06-15"
        )
        == "Hello world"
    )


def test_strip_source_prefix_no_prefix_returns_original():
    """无前缀时应返回原文。"""
    assert _strip_source_prefix("Hello world", "2024-06-15") == "Hello world"


def test_word_in_text_boundary_matching():
    """单词边界匹配检测。"""
    assert _word_in_text("seat", "I like seat 45") is True
    assert _word_in_text("seat", "theseats") is False


def test_clean_search_result_removes_internal_keys():
    """应移除内部字段并解码分隔符。"""
    r = {
        "_merged_indices": [0, 1],
        "_meta_idx": 0,
        "faiss_id": 1,
        "text": "a\x00b",
        "score": 0.9,
    }
    _clean_search_result(r)
    assert "_merged_indices" not in r
    assert "_meta_idx" not in r
    assert "faiss_id" not in r
    assert r["text"] == "a; b"


def test_clean_search_result_no_delimiter_unchanged():
    """无分隔符时 text 不变。"""
    r = {"text": "hello world", "score": 0.9}
    _clean_search_result(r)
    assert r["text"] == "hello world"


def test_adaptive_chunk_few_entries_returns_default():
    """不足 10 条时回退 DEFAULT_CHUNK_SIZE=1500。"""
    popped = os.environ.pop("MEMORYBANK_CHUNK_SIZE", None)
    try:
        meta = [{"text": "hello"}] * 5
        assert _get_effective_chunk_size(meta) == DEFAULT_CHUNK_SIZE
    finally:
        if popped is not None:
            os.environ["MEMORYBANK_CHUNK_SIZE"] = popped


def test_update_memory_strength_refreshes_recall_date():
    """验证检索命中后 last_recall_date 被刷新。"""
    meta = [
        {
            "faiss_id": 0,
            "memory_strength": 1,
            "last_recall_date": "2024-01-01",
        },
    ]
    results = [
        {"_meta_idx": 0, "_all_meta_indices": [0], "score": 0.9},
    ]
    updated = _update_memory_strengths(results, meta)
    assert updated
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    assert meta[0]["last_recall_date"] == today


def test_memory_strength_no_cap():
    """验证记忆强度可以超过 10（原版行为）。"""
    meta = [
        {
            "faiss_id": 0,
            "memory_strength": 9.5,
            "last_recall_date": "2024-01-01",
            "text": "test",
            "timestamp": "2024-01-01T00:00:00",
        },
    ]
    results = [
        {"_meta_idx": 0, "score": 1.0, "_merged_indices": [0]},
    ]
    _update_memory_strengths(results, meta)
    assert meta[0]["memory_strength"] == 10.5, (
        f"expected 10.5, got {meta[0]['memory_strength']}"
    )
    _update_memory_strengths(results, meta)
    assert meta[0]["memory_strength"] == 11.5, (
        f"expected 11.5, got {meta[0]['memory_strength']}"
    )


@pytest.mark.asyncio
async def test_pipeline_returns_results_without_retention_weight():
    """验证移除 retention weight 后检索管道仍正常返回结果。"""
    with tempfile.TemporaryDirectory() as tmp:
        idx = FaissIndex(Path(tmp))
        await idx.load()
        await idx.add_vector(
            "entry 0: test preference",
            [0.1] * 1536,
            "2024-01-01T00:00:00",
            {
                "source": "2024-01-01",
                "speakers": ["User"],
                "memory_strength": 1,
                "last_recall_date": "2024-01-01",
            },
        )
        await idx.add_vector(
            "entry 1: other topic",
            [0.2] * 1536,  # 不同向量使相似度不同
            "2024-06-14T00:00:00",
            {
                "source": "2024-06-14",
                "speakers": ["User"],
                "memory_strength": 5,
                "last_recall_date": "2024-06-14",
            },
        )
        mock_emb = AsyncMock(spec=["encode"])
        # query 与 entry 0 相似
        mock_emb.encode = AsyncMock(return_value=[0.1] * 1536)
        pipe = RetrievalPipeline(idx, mock_emb)
        results = await pipe.search("test preference", top_k=2)
        assert len(results) >= 1


def test_adaptive_chunk_many_entries_uses_p90():
    """10 条以上时基于 P90 ×3 计算。"""
    popped = os.environ.pop("MEMORYBANK_CHUNK_SIZE", None)
    try:
        meta = [{"text": "x" * n} for n in range(1, 101)]
        sz = _get_effective_chunk_size(meta)
        assert sz == 270
    finally:
        if popped is not None:
            os.environ["MEMORYBANK_CHUNK_SIZE"] = popped
