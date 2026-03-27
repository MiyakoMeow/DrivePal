"""Tests for the embedding model."""

import torch

import pytest

from app.memory.memory import MemoryModule
from app.memory.memory_bank import (
    AGGREGATION_SIMILARITY_THRESHOLD,
    MemoryBankBackend,
)
from app.memory.utils import cosine_similarity
from app.models.embedding import EmbeddingModel


def _pick_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


@pytest.fixture(scope="module")
def embedding():
    """Provide a shared EmbeddingModel instance for the module."""
    return EmbeddingModel(device=_pick_device())


class TestEmbeddingForMemorySearch:

    """Tests for embedding-based memory search."""

    def test_semantic_match_retrieves(self, embedding, tmp_path):
        """Verify that semantically similar queries retrieve the correct memory."""
        memory = MemoryModule(str(tmp_path), embedding_model=embedding)
        memory.write({"content": "明天下午三点项目评审会议"})
        results = memory.search("项目评审下午三点", mode="embeddings")
        assert len(results) == 1

    def test_semantic_miss_skips(self, embedding, tmp_path):
        """Verify that semantically unrelated queries return no results."""
        memory = MemoryModule(str(tmp_path), embedding_model=embedding)
        memory.write({"content": "明天下午三点项目评审会议"})
        results = memory.search("天气预报查询", mode="embeddings")
        assert results == []


class TestEmbeddingForMemoryBankRetrieval:

    """Tests for embedding-based memory bank retrieval with forgetting."""

    def test_forgetting_weighted_ranking(self, embedding, tmp_path):
        """Verify that search results are ranked by weighted memory strength."""
        backend = MemoryBankBackend(str(tmp_path), embedding_model=embedding)
        backend.write_with_memory({"content": "重要项目进度讨论"})
        results = backend.search("项目进度")
        assert len(results) > 0
        assert results[0]["_score"] > 0

    def test_low_similarity_below_keyword_threshold(self, embedding, tmp_path):
        """Verify that low-similarity results have a score below the keyword threshold."""
        backend = MemoryBankBackend(str(tmp_path), embedding_model=embedding)
        backend.write_with_memory({"content": "明天下午三点项目评审会议"})
        results = backend.search("今晚吃什么好呢")
        assert len(results) > 0
        assert results[0]["_score"] < 0.5


class TestEmbeddingForEventAggregation:

    """Tests for embedding-based event aggregation."""

    def test_similar_query_appends_to_event(self, embedding, tmp_path):
        """Verify that similar interactions are aggregated into the same event."""
        backend = MemoryBankBackend(str(tmp_path), embedding_model=embedding)
        backend.write_interaction("提醒明天上午九点开会", "好的已添加")
        backend.write_interaction("会议提醒明天上午九点", "已确认")
        events = backend.events_store.read()
        assert len(events) == 1
        assert len(events[0]["interaction_ids"]) == 2

    def test_unrelated_query_creates_new_event(self, embedding, tmp_path):
        """Verify that unrelated interactions create separate events."""
        backend = MemoryBankBackend(str(tmp_path), embedding_model=embedding)
        backend.write_interaction("提醒明天上午九点开会", "好的已添加")
        backend.write_interaction("今天天气怎么样", "晴天适合出行")
        events = backend.events_store.read()
        assert len(events) == 2

    def test_aggregation_threshold_enforced(self, embedding, tmp_path):
        """Verify that the aggregation similarity threshold is correctly enforced."""
        m = MemoryModule(str(tmp_path), embedding_model=embedding)
        assert m.embedding_model is not None
        similar = m.embedding_model.encode("提醒明天上午九点开会")
        unrelated = m.embedding_model.encode("今天天气怎么样")
        s_similar = cosine_similarity(similar, similar)
        s_unrelated = cosine_similarity(similar, unrelated)
        assert s_similar >= AGGREGATION_SIMILARITY_THRESHOLD
        assert s_unrelated < AGGREGATION_SIMILARITY_THRESHOLD
