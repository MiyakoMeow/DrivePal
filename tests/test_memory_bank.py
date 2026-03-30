"""记忆库后端和集成测试."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.memory.schemas import MemoryEvent
from app.memory.components import DAILY_SUMMARY_THRESHOLD, OVERALL_SUMMARY_THRESHOLD
from app.memory.stores.memory_bank_store import MemoryBankStore

from app.memory.memory import MemoryModule
from app.memory.types import MemoryMode
from tests.conftest import SKIP_IF_NO_LLM


@pytest.fixture
def backend(tmp_path: Path) -> MemoryBankStore:
    """提供由临时目录支持的 MemoryBankStore 实例."""
    return MemoryBankStore(tmp_path)


@pytest.fixture
def mock_chat_model() -> MagicMock:
    """提供返回固定摘要字符串的模拟 ChatModel."""
    chat = MagicMock()
    chat.generate.return_value = "测试摘要"
    return chat


class TestSearchWithForgetting:
    """带遗忘机制的搜索行为测试."""

    def test_search_no_embedding_returns_keyword(
        self, backend: MemoryBankStore
    ) -> None:
        """验证无嵌入时搜索回退到关键词匹配."""
        backend.write(MemoryEvent(content="今天天气很好"))
        results = backend.search("天气")
        assert len(results) > 0
        assert "天气" in results[0].event["content"]

    def test_search_empty_events(self, backend: MemoryBankStore) -> None:
        """验证无事件时搜索返回空列表."""
        assert backend.search("测试") == []

    def test_search_returns_top_k(self, backend: MemoryBankStore) -> None:
        """验证搜索结果限制为 top-k 结果."""
        for i in range(10):
            backend.write(MemoryEvent(content=f"事件{i}关于天气"))
        results = backend.search("天气")
        assert len(results) <= 10


class TestRecallStrengthening:
    """基于回忆的记忆强化测试."""

    def test_search_increases_memory_strength(self, backend: MemoryBankStore) -> None:
        """验证搜索事件增加其记忆强度."""
        backend.write(MemoryEvent(content="重要的会议"))
        backend.search("会议")
        events = backend.events_store.read()
        assert events[0]["memory_strength"] == 2

    def test_search_updates_only_matched_events(self, backend: MemoryBankStore) -> None:
        """验证只有匹配事件的记忆强度被更新."""
        backend.write(MemoryEvent(content="关于天气的事件"))
        backend.write(MemoryEvent(content="关于会议的事件"))
        backend.search("天气")
        events = backend.events_store.read()
        weather = [e for e in events if "天气" in e["content"]][0]
        meeting = [e for e in events if "会议" in e["content"]][0]
        assert weather["memory_strength"] == 2
        assert meeting["memory_strength"] == 1


class TestHierarchicalSummarization:
    """层次化每日和总体摘要测试."""

    def test_summarize_trigger_threshold(
        self, tmp_path: Path, mock_chat_model: MagicMock
    ) -> None:
        """验证每日摘要在天数达到阈值时触发."""
        backend = MemoryBankStore(tmp_path, chat_model=mock_chat_model)
        for i in range(DAILY_SUMMARY_THRESHOLD):
            backend.write(MemoryEvent(content=f"事件{i}"))
        summaries = backend.summaries_store.read()
        today = backend.events_store.read()[0]["date_group"]
        assert today in summaries["daily_summaries"]
        assert mock_chat_model.generate.called

    def test_no_summary_below_threshold(
        self, tmp_path: Path, mock_chat_model: MagicMock
    ) -> None:
        """验证低于事件阈值时不创建每日摘要."""
        backend = MemoryBankStore(tmp_path, chat_model=mock_chat_model)
        for i in range(DAILY_SUMMARY_THRESHOLD - 1):
            backend.write(MemoryEvent(content=f"事件{i}"))
        summaries = backend.summaries_store.read()
        assert len(summaries["daily_summaries"]) == 0

    def test_overall_summary_trigger(
        self, tmp_path: Path, mock_chat_model: MagicMock
    ) -> None:
        """验证当每日摘要达到阈值时触发总体摘要."""
        mock_chat_model.generate.return_value = "总体摘要"
        backend = MemoryBankStore(tmp_path, chat_model=mock_chat_model)
        summaries = backend.summaries_store.read()
        for i in range(OVERALL_SUMMARY_THRESHOLD):
            date_group = f"2026-03-{20 + i:02d}"
            summaries["daily_summaries"][date_group] = {
                "content": f"每日摘要{i}",
                "memory_strength": 1,
                "last_recall_date": date_group,
            }
        backend.summaries_store.write(summaries)
        backend._engine._update_overall_summary(summaries["daily_summaries"], summaries)
        updated = backend.summaries_store.read()
        assert updated["overall_summary"] == "总体摘要"

    def test_summaries_included_in_search(
        self, tmp_path: Path, mock_chat_model: MagicMock
    ) -> None:
        """验证每日摘要包含在搜索结果中."""
        mock_chat_model.generate.return_value = "今天讨论了项目进度"
        backend = MemoryBankStore(tmp_path, chat_model=mock_chat_model)
        for i in range(DAILY_SUMMARY_THRESHOLD):
            backend.write(MemoryEvent(content=f"事件{i}关于项目"))
        results = backend.search("讨论了")
        sources = [r.source for r in results]
        assert "daily_summary" in sources


class TestUpdateEventSummary:
    """基于 LLM 的事件摘要更新测试."""

    def test_llm_updates_event_content(
        self, tmp_path: Path, mock_chat_model: MagicMock
    ) -> None:
        """验证 LLM 在聚合时生成更新后的事件摘要."""
        mock_chat_model.generate.return_value = "用户修改了会议时间"
        backend = MemoryBankStore(tmp_path, chat_model=mock_chat_model)
        backend.write_interaction("提醒我明天上午开会", "好的", event_type="meeting")
        backend.write_interaction("明天下午也有会议", "已更新")
        events = backend.events_store.read()
        assert len(events) == 1
        assert events[0]["content"] == "用户修改了会议时间"

    def test_no_llm_preserves_original(self, backend: MemoryBankStore) -> None:
        """验证无 LLM 时保留原始内容."""
        backend.write_interaction("提醒我明天上午开会", "好的")
        backend.write_interaction("明天下午也有会议", "已更新")
        events = backend.events_store.read()
        assert events[0]["content"] == "提醒我明天上午开会"


@SKIP_IF_NO_LLM
class TestMemoryModuleIntegration:
    """MemoryModule 与记忆库的完整集成测试."""

    def test_write_interaction_flow(self, tmp_path: Path) -> None:
        """验证端到端的写入交互和搜索流程."""
        memory = MemoryModule(tmp_path)
        memory.write_interaction("测试查询", "测试回复")
        results = memory.search("测试", mode=MemoryMode.MEMORY_BANK)
        assert len(results) > 0
        assert len(results[0].interactions) >= 1
