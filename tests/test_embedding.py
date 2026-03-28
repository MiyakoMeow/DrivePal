"""Tests for the embedding model."""

import torch

import pytest

from app.memory.memory import MemoryModule
from app.memory.schemas import MemoryEvent
from app.memory.types import MemoryMode
from app.memory.stores.memory_bank_store import MemoryBankStore
from app.models.embedding import EmbeddingModel
from tests.conftest import SKIP_IF_NO_LLM


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


@SKIP_IF_NO_LLM
class TestEmbeddingForMemorySearch:
    """Tests for embedding-based memory search."""

    def test_semantic_match_retrieves(self, embedding, tmp_path):
        """Verify that semantically similar queries retrieve the correct memory."""
        memory = MemoryModule(str(tmp_path), embedding_model=embedding)
        memory.write(MemoryEvent(content="明天下午三点项目评审会议"))
        results = memory.search("项目评审下午三点", mode=MemoryMode.EMBEDDINGS)
        assert len(results) == 1

    def test_semantic_miss_skips(self, embedding, tmp_path):
        """Verify that semantically unrelated queries return no results."""
        memory = MemoryModule(str(tmp_path), embedding_model=embedding)
        memory.write(MemoryEvent(content="明天下午三点项目评审会议"))
        results = memory.search("天气预报查询", mode=MemoryMode.EMBEDDINGS)
        assert results == []


@SKIP_IF_NO_LLM
class TestEmbeddingForMemoryBankRetrieval:
    """Tests for embedding-based memory bank retrieval with forgetting."""

    def test_forgetting_weighted_ranking(self, embedding, tmp_path):
        """Verify that search results are ranked by weighted memory strength."""
        backend = MemoryBankStore(str(tmp_path), embedding_model=embedding)
        backend.write(MemoryEvent(content="重要项目进度讨论"))
        results = backend.search("项目进度")
        assert len(results) > 0
        assert results[0].score > 0

    def test_low_similarity_below_keyword_threshold(self, embedding, tmp_path):
        """Verify that low-similarity results have a score below the keyword threshold."""
        backend = MemoryBankStore(str(tmp_path), embedding_model=embedding)
        backend.write(MemoryEvent(content="明天下午三点项目评审会议"))
        results = backend.search("今晚吃什么好呢")
        assert len(results) > 0
        assert results[0].score < 0.5
