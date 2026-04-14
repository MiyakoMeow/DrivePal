"""记忆库后端和集成测试."""

import inspect
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.memory.memory import MemoryModule
from app.memory.schemas import MemoryEvent, SearchResult
from app.memory.stores.memory_bank import MemoryBankStore
from app.memory.stores.memory_bank.summarization import (
    DAILY_SUMMARY_THRESHOLD,
    SummaryManager,
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

    async def test_daily_summary_prompt_is_english(self) -> None:
        """验证 daily summary prompt 包含英文车辆偏好提取指令."""
        source = inspect.getsource(SummaryManager.maybe_summarize)
        assert "vehicle-related preferences" in source

    async def test_overall_summary_prompt_is_english(self) -> None:
        """验证 overall summary prompt 包含英文偏好合并指令."""
        source = inspect.getsource(SummaryManager.update_overall_summary)
        assert "preference profile" in source


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


class TestNameBonus:
    """搜索评分名称共现加分测试."""

    async def test_name_bonus_boosts_matching_results(
        self,
        backend: MemoryBankStore,
    ) -> None:
        """验证 _apply_name_bonus 对包含匹配名称的结果加分."""
        known_names = frozenset({"alice", "bob"})
        r_alice = SearchResult(event={"content": "Alice: seat"}, score=1.0)
        r_bob = SearchResult(event={"content": "Bob: seat"}, score=1.0)
        backend._engine._apply_name_bonus([r_alice, r_bob], known_names, "Alice seat")
        assert r_alice.score > r_bob.score
        expected_bonus = 1.0 * 1.3
        assert r_alice.score == expected_bonus
        assert r_bob.score == 1.0

    async def test_name_bonus_no_effect_without_names(
        self,
        backend: MemoryBankStore,
    ) -> None:
        """验证 query 不含已知名称时不触发加分."""
        await backend.write(
            MemoryEvent(content="Alice: I like green seats", date_group="2025-03-01"),
        )
        await backend.write(
            MemoryEvent(
                content="Bob: I prefer blue dashboard", date_group="2025-03-01"
            ),
        )
        results = await backend.search("seat")
        assert len(results) >= 1
