"""嵌入模型测试."""

from typing import TYPE_CHECKING

import pytest

from app.memory.enricher import OverallContextEnricher
from app.memory.memory import MemoryModule
from app.memory.schemas import MemoryEvent
from app.memory.stores.memory_bank import MemoryBankStore
from app.memory.stores.memory_bank.faiss_index import FaissIndex
from app.memory.stores.memory_bank.forget import ForgettingCurve
from app.memory.stores.memory_bank.retrieval import RetrievalPipeline
from app.memory.types import MemoryMode

if TYPE_CHECKING:
    from pathlib import Path

    from app.models.embedding import EmbeddingModel

SIMILARITY_THRESHOLD = 0.6


@pytest.mark.embedding
class TestEmbeddingForMemorySearch:
    """基于嵌入的记忆搜索测试."""

    async def test_semantic_match_retrieves(
        self,
        embedding: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        """验证语义相似的查询检索到正确的记忆."""
        memory = MemoryModule(tmp_path, embedding_model=embedding)
        await memory.write(MemoryEvent(content="明天下午三点项目评审会议"))
        results = await memory.search("项目评审下午三点", mode=MemoryMode.MEMORY_BANK)
        assert len(results) == 1

    async def test_semantic_miss_skips(
        self,
        embedding: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        """验证语义无关的查询返回低分结果."""
        memory = MemoryModule(tmp_path, embedding_model=embedding)
        await memory.write(MemoryEvent(content="明天下午三点项目评审会议"))
        results = await memory.search("天气预报查询", mode=MemoryMode.MEMORY_BANK)
        if results:
            assert results[0].score < SIMILARITY_THRESHOLD


@pytest.mark.embedding
class TestEmbeddingForMemoryBankRetrieval:
    """带遗忘的基于嵌入的记忆库检索测试."""

    @pytest.fixture
    def bank_store(
        self,
        embedding: EmbeddingModel,
        tmp_path: Path,
    ) -> MemoryBankStore:
        """提供真实 embedding 的 MemoryBankStore 实例。"""
        index = FaissIndex(tmp_path)
        retrieval = RetrievalPipeline(index, embedding)
        forgetting = ForgettingCurve()
        enricher = OverallContextEnricher()
        return MemoryBankStore(
            index=index,
            retrieval=retrieval,
            embedding_model=embedding,
            enricher=enricher,
            forgetting=forgetting,
        )

    async def test_forgetting_weighted_ranking(
        self,
        bank_store: MemoryBankStore,
    ) -> None:
        """验证搜索结果按加权记忆强度排名."""
        await bank_store.write(MemoryEvent(content="重要项目进度讨论"))
        results = await bank_store.search("项目进度")
        assert len(results) > 0
        assert results[0].score > 0

    async def test_low_similarity_below_keyword_threshold(
        self,
        bank_store: MemoryBankStore,
    ) -> None:
        """验证低相似度结果的分数低于关键词阈值."""
        await bank_store.write(MemoryEvent(content="明天下午三点项目评审会议"))
        results = await bank_store.search("今晚吃什么好呢")
        if results:
            assert results[0].score < SIMILARITY_THRESHOLD
