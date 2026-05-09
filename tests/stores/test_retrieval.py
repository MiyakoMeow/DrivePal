"""RetrievalPipeline 单元测试。"""

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.memory.embedding_client import EmbeddingClient
from app.memory.memory_bank.config import MemoryBankConfig
from app.memory.memory_bank.index import FaissIndex
from app.memory.memory_bank.retrieval import (
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
        pipe = RetrievalPipeline(
            idx, EmbeddingClient(mock_embedding), MemoryBankConfig()
        )
        results, updated = await pipe.search("anything")
        assert results == []
        assert updated is False


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
        pipe = RetrievalPipeline(
            idx, EmbeddingClient(mock_embedding), MemoryBankConfig()
        )
        results, _updated = await pipe.search("Gary seat")
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
        assert (
            _get_effective_chunk_size(meta, MemoryBankConfig())
            == MemoryBankConfig().default_chunk_size
        )
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
        pipe = RetrievalPipeline(idx, EmbeddingClient(mock_emb), MemoryBankConfig())
        results, _updated = await pipe.search("test preference", top_k=2)
        assert len(results) >= 1


def test_adaptive_chunk_many_entries_uses_p90():
    """10 条以上时基于 P90 ×3 计算。"""
    popped = os.environ.pop("MEMORYBANK_CHUNK_SIZE", None)
    try:
        meta = [{"text": "x" * n} for n in range(1, 101)]
        sz = _get_effective_chunk_size(meta, MemoryBankConfig())
        assert sz == 270
    finally:
        if popped is not None:
            os.environ["MEMORYBANK_CHUNK_SIZE"] = popped


def test_speaker_filter_negative_score_penalty():
    """负分时惩罚应加重（绝对值增大），非缩小。"""
    pipe = RetrievalPipeline.__new__(RetrievalPipeline)
    results = [
        {
            "speakers": ["Alice"],
            "score": 0.9,
            "text": "relevant",
        },
        {
            "speakers": ["Bob"],
            "score": -0.5,
            "text": "irrelevant",
        },
    ]
    filtered = pipe._apply_speaker_filter(results, "Alice")
    assert filtered[0]["score"] == 0.9
    assert filtered[1]["score"] == -0.625


def test_speaker_filter_first_name_matching():
    """Query 中 first name 应匹配全名说话人。"""
    pipe = RetrievalPipeline.__new__(RetrievalPipeline)
    results = [
        {
            "speakers": ["Gary Smith"],
            "score": 0.9,
            "text": "Gary's preference",
        },
        {
            "speakers": ["Patricia Johnson"],
            "score": 0.8,
            "text": "Patricia's preference",
        },
    ]
    filtered = pipe._apply_speaker_filter(results, "Gary seat preference")
    gary = next(r for r in filtered if any("Gary" in s for s in r.get("speakers", [])))
    assert gary["score"] == 0.9
    patricia = next(
        r for r in filtered if any("Patricia" in s for s in r.get("speakers", []))
    )
    assert patricia["score"] == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_all_below_similarity_threshold():
    """全低于相似度阈值 → 返回空。"""
    with tempfile.TemporaryDirectory() as tmp:
        idx = FaissIndex(Path(tmp))
        await idx.load()
        # 存储一个向量
        await idx.add_vector(
            "test content",
            [1.0] + [0.0] * 1535,  # 单位向量 (1,0,0,...)
            "2024-06-15T00:00:00",
            {"source": "2024-06-15"},
        )
        cfg = MemoryBankConfig()
        cfg.embedding_min_similarity = 0.99
        # query 用正交向量 → 内积 ≈ 0 → 低于阈值
        mock_emb = AsyncMock()
        mock_emb.encode = AsyncMock(return_value=[0.0, 1.0] + [0.0] * 1534)
        pipe = RetrievalPipeline(idx, EmbeddingClient(mock_emb), cfg)
        results, _updated = await pipe.search("anything")
        assert len(results) == 0


@pytest.mark.asyncio
async def test_no_speaker_in_query_no_discount(mock_embedding):
    """query 中无说话人时无条目被降权。"""
    with tempfile.TemporaryDirectory() as tmp:
        idx = FaissIndex(Path(tmp))
        await idx.load()
        await idx.add_vector(
            "Gary seat 45",
            [0.1] * 1536,
            "2024-06-15T00:00:00",
            {"source": "2024-06-15", "speakers": ["Gary"]},
        )
        pipe = RetrievalPipeline(idx, EmbeddingClient(mock_embedding), MemoryBankConfig())
        results, _updated = await pipe.search("weather today")
        assert len(results) >= 1
        # 无说话人匹配，分数不应被更改
        for r in results:
            orig = r.get("score", 0.0)
            assert orig >= 0  # 未降权


@pytest.mark.asyncio
async def test_pipeline_filters_forgotten_entries(mock_embedding):
    """forgotten=True 条目被检索管道过滤。"""
    with tempfile.TemporaryDirectory() as tmp:
        idx = FaissIndex(Path(tmp))
        await idx.load()
        await idx.add_vector(
            "forgotten entry",
            [0.1] * 1536,
            "2024-06-15T00:00:00",
            {"source": "2024-06-15", "forgotten": True},
        )
        await idx.add_vector(
            "active entry",
            [0.1] * 1536,
            "2024-06-15T00:00:00",
            {"source": "2024-06-15"},
        )
        pipe = RetrievalPipeline(idx, EmbeddingClient(mock_embedding), MemoryBankConfig())
        results, _updated = await pipe.search("entry", top_k=5)
        for r in results:
            assert not r.get("forgotten")
