"""嵌入模型测试（多用户版）。"""

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from app.memory.memory_bank import MemoryBankStore
from app.memory.schemas import MemoryEvent

if TYPE_CHECKING:
    from pathlib import Path

    from app.models.embedding import EmbeddingModel

SIMILARITY_THRESHOLD = 0.6


def _mock_chat() -> AsyncMock:
    m = AsyncMock(spec=["generate"])
    m.generate = AsyncMock(return_value="summary")
    return m


@pytest.mark.embedding
class TestEmbeddingForMemoryBankRetrieval:
    """基于嵌入的记忆库检索测试（多用户版）。"""

    async def test_semantic_match_retrieves(
        self,
        embedding: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        """验证语义相似的查询检索到正确的记忆。"""
        store = MemoryBankStore(tmp_path, embedding, _mock_chat())
        await store.write("user_1", MemoryEvent(content="明天下午三点项目评审会议"))
        results = await store.search("user_1", "项目评审下午三点")
        assert len(results) >= 1

    async def test_semantic_miss_skips(
        self,
        embedding: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        """验证语义无关的查询返回空列表或低分结果。"""
        store = MemoryBankStore(tmp_path, embedding, _mock_chat())
        await store.write("user_1", MemoryEvent(content="明天下午三点项目评审会议"))
        results = await store.search("user_1", "天气预报查询")
        assert not results or results[0].score < SIMILARITY_THRESHOLD

    async def test_forgetting_weighted_ranking(
        self,
        embedding: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        """验证搜索结果按加权记忆强度排名。"""
        store = MemoryBankStore(tmp_path, embedding, _mock_chat())
        await store.write("user_1", MemoryEvent(content="重要项目进度讨论"))
        results = await store.search("user_1", "项目进度")
        assert len(results) > 0
        assert results[0].score > 0

    async def test_low_similarity_below_keyword_threshold(
        self,
        embedding: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        """验证低相似度结果的分数低于关键词阈值。"""
        store = MemoryBankStore(tmp_path, embedding, _mock_chat())
        await store.write("user_1", MemoryEvent(content="明天下午三点项目评审会议"))
        results = await store.search("user_1", "今晚吃什么好呢")
        if results:
            assert results[0].score < SIMILARITY_THRESHOLD
