"""嵌入模型测试."""

from typing import TYPE_CHECKING

import pytest

from app.memory.memory import MemoryModule
from app.memory.memory_bank import MemoryBankStore
from app.memory.schemas import MemoryEvent
from app.memory.types import MemoryMode

if TYPE_CHECKING:
    from pathlib import Path

    from app.models.embedding import EmbeddingModel

SIMILARITY_THRESHOLD = 0.6


def test_embedding_model_uses_batch_size():
    """EmbeddingModel 接受 batch_size 参数并存储"""
    from app.models.embedding import EmbeddingModel
    from app.models.settings import EmbeddingProviderConfig
    from app.models.types import ProviderConfig

    cfg = EmbeddingProviderConfig(
        provider=ProviderConfig(model="test", base_url="http://x", api_key="k")
    )
    model = EmbeddingModel(provider=cfg, batch_size=50)
    assert model.batch_size == 50


def test_embedding_model_default_batch_size():
    """默认 batch_size 为 32"""
    from app.models.embedding import EmbeddingModel
    from app.models.settings import EmbeddingProviderConfig
    from app.models.types import ProviderConfig

    cfg = EmbeddingProviderConfig(
        provider=ProviderConfig(model="test", base_url="http://x", api_key="k")
    )
    model = EmbeddingModel(provider=cfg)
    assert model.batch_size == 32


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

    async def test_forgetting_weighted_ranking(
        self,
        embedding: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        """验证搜索结果按加权记忆强度排名."""
        backend = MemoryBankStore(tmp_path, embedding_model=embedding)
        await backend.write(MemoryEvent(content="重要项目进度讨论"))
        results = await backend.search("项目进度")
        assert len(results) > 0
        assert results[0].score > 0

    async def test_low_similarity_below_keyword_threshold(
        self,
        embedding: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        """验证低相似度结果的分数低于关键词阈值."""
        backend = MemoryBankStore(tmp_path, embedding_model=embedding)
        await backend.write(MemoryEvent(content="明天下午三点项目评审会议"))
        results = await backend.search("今晚吃什么好呢")
        if results:
            assert results[0].score < SIMILARITY_THRESHOLD
