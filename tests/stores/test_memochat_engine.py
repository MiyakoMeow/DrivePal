"""MemoChatEngine 测试."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.memory.stores.memochat.engine import (
    MemoChatEngine,
    RECENT_DIALOGS_KEEP_AFTER_SUMMARY,
    SUMMARIZATION_TURN_THRESHOLD,
)
from app.memory.stores.memochat.retriever import RetrievalMode


@pytest.fixture
def mock_chat() -> MagicMock:
    chat = MagicMock()
    chat.generate = AsyncMock()
    return chat


@pytest.fixture
def mock_embedding() -> MagicMock:
    emb = MagicMock()
    emb.encode = AsyncMock(return_value=[0.1] * 10)
    emb.batch_encode = AsyncMock(return_value=[[0.1] * 10])
    return emb


@pytest.fixture
def engine(
    tmp_path: Path, mock_chat: MagicMock, mock_embedding: MagicMock
) -> MemoChatEngine:
    return MemoChatEngine(tmp_path, mock_chat, mock_embedding, RetrievalMode.FULL_LLM)


class TestInit:
    async def test_recent_dialogs_initialized_on_empty(self, tmp_path: Path) -> None:
        eng = MemoChatEngine(tmp_path, MagicMock(), None, RetrievalMode.FULL_LLM)
        dialogs = await eng.read_recent_dialogs()
        assert len(dialogs) == 2
        assert dialogs[0].startswith("user:")
        assert dialogs[1].startswith("bot:")

    async def test_recent_dialogs_not_overwritten_if_exist(
        self, tmp_path: Path, mock_chat: MagicMock
    ) -> None:
        eng = MemoChatEngine(tmp_path, mock_chat, None, RetrievalMode.FULL_LLM)
        await eng.append_recent_dialog("user: test")
        eng2 = MemoChatEngine(tmp_path, mock_chat, None, RetrievalMode.FULL_LLM)
        dialogs = await eng2.read_recent_dialogs()
        assert any("test" in d for d in dialogs)


class TestAppendRecentDialog:
    async def test_appends_to_dialogs(self, engine: MemoChatEngine) -> None:
        await engine.append_recent_dialog("user: 你好")
        dialogs = await engine.read_recent_dialogs()
        assert "user: 你好" in dialogs


class TestSummarizeIfNeeded:
    async def test_no_summary_below_threshold(
        self, engine: MemoChatEngine, mock_chat: MagicMock
    ) -> None:
        for i in range(3):
            await engine.append_recent_dialog(f"user: 短消息{i}")
        await engine._summarize_if_needed()
        mock_chat.generate.assert_not_called()

    async def test_triggers_summary_on_turn_count(
        self, engine: MemoChatEngine, mock_chat: MagicMock
    ) -> None:
        mock_chat.generate.return_value = json.dumps(
            [{"topic": "测试", "summary": "简短摘要", "start": 1, "end": 3}]
        )
        dialogs = await engine.read_recent_dialogs()
        while len(dialogs) < SUMMARIZATION_TURN_THRESHOLD:
            await engine.append_recent_dialog("user: 填充内容")
            dialogs = await engine.read_recent_dialogs()
        await engine._summarize_if_needed()
        mock_chat.generate.assert_called_once()
        dialogs_after = await engine.read_recent_dialogs()
        assert len(dialogs_after) == RECENT_DIALOGS_KEEP_AFTER_SUMMARY

    async def test_writes_memos_on_summary(
        self, engine: MemoChatEngine, mock_chat: MagicMock
    ) -> None:
        mock_chat.generate.return_value = json.dumps(
            [{"topic": "天气", "summary": "用户讨论了天气", "start": 1, "end": 2}]
        )
        for i in range(SUMMARIZATION_TURN_THRESHOLD):
            await engine.append_recent_dialog(f"user: 今天天气不错{i}")
        await engine._summarize_if_needed()
        memos = await engine.read_memos()
        assert "天气" in memos

    async def test_fallback_noto_on_parse_failure(
        self, engine: MemoChatEngine, mock_chat: MagicMock
    ) -> None:
        mock_chat.generate.return_value = "无法解析的文本"
        for i in range(SUMMARIZATION_TURN_THRESHOLD):
            await engine.append_recent_dialog(f"user: 内容{i}")
        await engine._summarize_if_needed()
        memos = await engine.read_memos()
        assert "NOTO" in memos
        assert len(memos["NOTO"]) > 0

    async def test_no_truncation_on_llm_error(
        self, engine: MemoChatEngine, mock_chat: MagicMock
    ) -> None:
        mock_chat.generate.side_effect = RuntimeError("LLM unavailable")
        for i in range(SUMMARIZATION_TURN_THRESHOLD):
            await engine.append_recent_dialog(f"user: 内容{i}")
        dialogs_before = await engine.read_recent_dialogs()
        await engine._summarize_if_needed()
        dialogs_after = await engine.read_recent_dialogs()
        assert len(dialogs_after) == len(dialogs_before)


class TestSearch:
    async def test_search_returns_empty_without_memos(
        self, engine: MemoChatEngine, mock_chat: MagicMock
    ) -> None:
        mock_chat.generate.return_value = "1"
        results = await engine.search("天气")
        assert results == []

    async def test_search_returns_results_via_llm(
        self, engine: MemoChatEngine, mock_chat: MagicMock
    ) -> None:
        mock_chat.generate.return_value = json.dumps(
            [{"topic": "天气", "summary": "用户讨论了天气", "start": 1, "end": 2}]
        )
        for i in range(SUMMARIZATION_TURN_THRESHOLD):
            await engine.append_recent_dialog(f"user: 今天天气不错{i}")
        await engine._summarize_if_needed()
        assert mock_chat.generate.called
        mock_chat.generate.reset_mock()
        mock_chat.generate.return_value = "2"
        results = await engine.search("天气")
        assert len(results) == 1
        assert results[0].source == "event"

    async def test_search_returns_empty_on_empty_query(
        self, engine: MemoChatEngine
    ) -> None:
        results = await engine.search("")
        assert results == []
