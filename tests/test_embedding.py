"""嵌入模型测试."""

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
def embedding() -> EmbeddingModel:
    """为模块提供共享的 EmbeddingModel 实例."""
    return EmbeddingModel(device=_pick_device())


@SKIP_IF_NO_LLM
class TestEmbeddingForMemorySearch:
    """基于嵌入的记忆搜索测试."""

    def test_semantic_match_retrieves(
        self, embedding: EmbeddingModel, tmp_path: str
    ) -> None:
        """验证语义相似的查询检索到正确的记忆."""
        memory = MemoryModule(str(tmp_path), embedding_model=embedding)
        memory.write(MemoryEvent(content="明天下午三点项目评审会议"))
        results = memory.search("项目评审下午三点", mode=MemoryMode.EMBEDDINGS)
        assert len(results) == 1

    def test_semantic_miss_skips(
        self, embedding: EmbeddingModel, tmp_path: str
    ) -> None:
        """验证语义无关的查询返回低分结果."""
        memory = MemoryModule(str(tmp_path), embedding_model=embedding)
        memory.write(MemoryEvent(content="明天下午三点项目评审会议"))
        results = memory.search("天气预报查询", mode=MemoryMode.EMBEDDINGS)
        if results:
            assert results[0].score < 0.5


@SKIP_IF_NO_LLM
class TestEmbeddingForMemoryBankRetrieval:
    """带遗忘的基于嵌入的记忆库检索测试."""

    def test_forgetting_weighted_ranking(
        self, embedding: EmbeddingModel, tmp_path: str
    ) -> None:
        """验证搜索结果按加权记忆强度排名."""
        backend = MemoryBankStore(str(tmp_path), embedding_model=embedding)
        backend.write(MemoryEvent(content="重要项目进度讨论"))
        results = backend.search("项目进度")
        assert len(results) > 0
        assert results[0].score > 0

    def test_low_similarity_below_keyword_threshold(
        self, embedding: EmbeddingModel, tmp_path: str
    ) -> None:
        """验证低相似度结果的分数低于关键词阈值."""
        backend = MemoryBankStore(str(tmp_path), embedding_model=embedding)
        backend.write(MemoryEvent(content="明天下午三点项目评审会议"))
        results = backend.search("今晚吃什么好呢")
        assert len(results) > 0
        assert results[0].score < 0.5
