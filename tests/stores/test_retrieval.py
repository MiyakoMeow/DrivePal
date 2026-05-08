"""RetrievalPipeline 单元测试（多用户版）。"""

import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from app.memory.embedding_client import EmbeddingClient
from app.memory.memory_bank.faiss_index import FaissIndexManager
from app.memory.memory_bank.retrieval import (
    DEFAULT_CHUNK_SIZE,
    RetrievalPipeline,
    _clean_search_result,
    _compute_strength_updates,
    _get_effective_chunk_size,
    _merge_overlapping_results,
    _strip_source_prefix,
    _word_in_text,
)


@pytest.fixture
def manager(tmp_path: Path) -> FaissIndexManager:
    return FaissIndexManager(tmp_path)


@pytest.fixture
def mock_embedding():
    """Mock EmbeddingModel fixture。"""
    m = AsyncMock()
    m.encode.return_value = [0.1] * 1536
    return m


@pytest.mark.asyncio
async def test_search_empty_index_returns_empty(
    manager: FaissIndexManager, mock_embedding
):
    """空索引时 search 应返回空元组。"""
    pipe = RetrievalPipeline(manager, EmbeddingClient(mock_embedding))
    results, updates = await pipe.search("user_1", "anything")
    assert results == []
    assert updates == {}


@pytest.mark.asyncio
async def test_search_returns_results(manager: FaissIndexManager, mock_embedding):
    """有数据时 search 应返回结果。"""
    emb = [0.1] * 1536
    for _, text in enumerate(["Gary likes seat 45", "Patricia wants AC at 22"]):
        await manager.add_vector(
            "user_1",
            text,
            emb,
            "2024-06-15T10:00:00",
            {"source": "2024-06-15", "speakers": [text.split()[0]]},
        )
    pipe = RetrievalPipeline(manager, EmbeddingClient(mock_embedding))
    results, updates = await pipe.search("user_1", "Gary seat")
    assert len(results) >= 1
    assert isinstance(updates, dict)


@pytest.mark.asyncio
async def test_search_returns_strength_updates(
    manager: FaissIndexManager, mock_embedding
):
    """检索后应返回强度更新。"""
    emb = [0.1] * 1536
    await manager.add_vector(
        "user_1",
        "Gary likes seat 45",
        emb,
        "2024-06-15T10:00:00",
        {"source": "2024-06-15", "speakers": ["Gary"]},
    )
    pipe = RetrievalPipeline(manager, EmbeddingClient(mock_embedding))
    _, updates = await pipe.search("user_1", "Gary seat")
    assert len(updates) > 0
    # 验证更新字段
    for fields in updates.values():
        assert "memory_strength" in fields
        assert "last_recall_date" in fields


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


def test_compute_strength_updates_returns_dict():
    """_compute_strength_updates 返回更新字典而非原地修改。"""
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
    updates = _compute_strength_updates(results, meta)
    assert 0 in updates
    assert updates[0]["memory_strength"] == 2.0
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    assert updates[0]["last_recall_date"] == today
    # 验证未修改原 metadata
    assert meta[0]["memory_strength"] == 1.0


def test_memory_strength_no_cap():
    """验证记忆强度可以超过 10（纯函数版）。"""
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
    updates1 = _compute_strength_updates(results, meta)
    assert updates1[0]["memory_strength"] == 10.5
    updates2 = _compute_strength_updates(results, meta)
    # 原 metadata 未被修改，两次应得相同结果
    assert updates2[0]["memory_strength"] == 10.5


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


def test_speaker_filter_negative_score_penalty():
    """负分时惩罚应加重（绝对值增大），非缩小。"""
    pipe = RetrievalPipeline(MagicMock(), MagicMock())
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
    pipe = RetrievalPipeline(MagicMock(), MagicMock())
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
