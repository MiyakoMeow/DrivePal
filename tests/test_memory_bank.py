"""记忆库后端和集成测试."""

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.memory.memory import MemoryModule
from app.memory.schemas import MemoryEvent
from app.memory.stores.memory_bank import MemoryBankStore
from app.memory.stores.memory_bank.summarization import (
    DAILY_SUMMARY_THRESHOLD,
)
from app.memory.types import MemoryMode

if TYPE_CHECKING:
    from pathlib import Path

    from app.models.embedding import EmbeddingModel

TOP_K = 10
MEMORY_STRENGTH_AFTER_SEARCH = 2
MEMORY_STRENGTH_THRESHOLD = 2


@pytest.fixture
def backend(tmp_path: Path) -> MemoryBankStore:
    """提供由临时目录支持的 MemoryBankStore 实例."""
    return MemoryBankStore(tmp_path)


@pytest.fixture
def mock_chat_model() -> MagicMock:
    """提供返回固定摘要字符串的模拟 ChatModel."""
    chat = MagicMock()
    chat.generate = AsyncMock(return_value="测试摘要")
    return chat


class TestSearchWithForgetting:
    """带遗忘机制的搜索行为测试."""

    async def test_search_no_embedding_returns_keyword(
        self,
        backend: MemoryBankStore,
    ) -> None:
        """验证无嵌入时搜索回退到关键词匹配."""
        await backend.write(MemoryEvent(content="今天天气很好"))
        results = await backend.search("天气")
        assert len(results) > 0
        assert "天气" in results[0].event["content"]

    async def test_search_empty_events(self, backend: MemoryBankStore) -> None:
        """验证无事件时搜索返回空列表."""
        assert await backend.search("测试") == []

    async def test_search_returns_top_k(self, backend: MemoryBankStore) -> None:
        """验证搜索结果限制为 top-k 结果."""
        for i in range(10):
            await backend.write(MemoryEvent(content=f"事件{i}关于天气"))
        results = await backend.search("天气")
        assert len(results) == TOP_K


class TestRecallStrengthening:
    """基于回忆的记忆强化测试."""

    async def test_search_increases_memory_strength(
        self,
        backend: MemoryBankStore,
    ) -> None:
        """验证搜索事件增加其记忆强度."""
        await backend.write(MemoryEvent(content="重要的会议"))
        await backend.search("会议")
        events = await backend.events_store.read()
        assert events[0]["memory_strength"] == MEMORY_STRENGTH_AFTER_SEARCH

    async def test_search_updates_only_matched_events(
        self,
        backend: MemoryBankStore,
    ) -> None:
        """验证只有匹配事件的记忆强度被更新."""
        await backend.write(MemoryEvent(content="关于天气的事件"))
        await backend.write(MemoryEvent(content="关于会议的事件"))
        await backend.search("天气")
        events = await backend.events_store.read()
        weather = [e for e in events if "天气" in e["content"]][0]
        meeting = [e for e in events if "会议" in e["content"]][0]
        assert weather["memory_strength"] >= MEMORY_STRENGTH_THRESHOLD
        assert meeting["memory_strength"] == 1


class TestHierarchicalSummarization:
    """层次化每日和总体摘要测试."""

    async def test_summaries_included_in_search(
        self,
        tmp_path: Path,
        mock_chat_model: MagicMock,
    ) -> None:
        """验证每日摘要包含在搜索结果中."""
        mock_chat_model.generate.return_value = "今天讨论了项目进度"
        backend = MemoryBankStore(tmp_path, chat_model=mock_chat_model)
        for i in range(DAILY_SUMMARY_THRESHOLD):
            await backend.write(MemoryEvent(content=f"事件{i}关于项目"))
        results = await backend.search("讨论了")
        sources = [r.source for r in results]
        assert "daily_summary" in sources

    async def test_no_summary_below_threshold(
        self,
        tmp_path: Path,
        mock_chat_model: MagicMock,
    ) -> None:
        """验证低于事件阈值时不创建每日摘要."""
        backend = MemoryBankStore(tmp_path, chat_model=mock_chat_model)
        for i in range(DAILY_SUMMARY_THRESHOLD - 1):
            await backend.write(MemoryEvent(content=f"事件{i}"))
        summaries = await backend.summaries_store.read()
        assert len(summaries["daily_summaries"]) == 0


class TestUpdateEventSummary:
    """基于 LLM 的事件摘要更新测试."""

    async def test_no_llm_preserves_original(self, backend: MemoryBankStore) -> None:
        """验证无 LLM 时保留原始内容."""
        await backend.write_interaction("提醒我明天上午开会", "好的")
        await backend.write_interaction("明天下午也有会议", "已更新")
        events = await backend.events_store.read()
        assert events[0]["content"] == "提醒我明天上午开会"


@pytest.mark.llm
@pytest.mark.embedding
@pytest.mark.usefixtures("llm_provider")
class TestMemoryModuleIntegration:
    """MemoryModule 与记忆库的完整集成测试.

    使用 usefixtures("llm_provider") 确保 LLM 配置可用，
    因为 MemoryBankStore.requires_chat=True 会惰性初始化 ChatModel。
    """

    async def test_write_interaction_flow(
        self,
        tmp_path: Path,
        embedding: EmbeddingModel,
    ) -> None:
        """验证端到端的写入交互和搜索流程."""
        memory = MemoryModule(tmp_path, embedding_model=embedding)
        await memory.write_interaction("测试查询", "测试回复")
        results = await memory.search("测试", mode=MemoryMode.MEMORY_BANK)
        assert len(results) > 0
        assert len(results[0].interactions) >= 1
