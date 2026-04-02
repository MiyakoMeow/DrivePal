"""MemoChat 检索策略测试."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.memory.stores.memochat.retriever import (
    retrieve_full_llm,
    retrieve_hybrid,
)


@pytest.fixture
def mock_chat() -> MagicMock:
    chat = MagicMock()
    chat.generate = AsyncMock()
    return chat


@pytest.fixture
def mock_embedding() -> MagicMock:
    emb = MagicMock()
    emb.encode = AsyncMock(return_value=[0.1] * 10)
    emb.batch_encode = AsyncMock(return_value=[[0.1] * 10, [0.9] * 10, [0.1] * 10])
    return emb


MEMOS_SAMPLE: dict[str, list[dict]] = {
    "天气": [
        {"id": "id1", "summary": "用户讨论了天气", "dialogs": ["user: 今天天气不错"]}
    ],
    "会议": [{"id": "id2", "summary": "用户有会议安排", "dialogs": ["user: 明天开会"]}],
    "NOTO": [{"id": "id3", "summary": "其他内容", "dialogs": ["user: 随便聊聊"]}],
}


class TestRetrieveFullLlm:
    async def test_returns_matching_topics(self, mock_chat: MagicMock) -> None:
        mock_chat.generate.return_value = "1"
        results = await retrieve_full_llm(mock_chat, "天气怎么样", MEMOS_SAMPLE, 5)
        assert len(results) == 1
        topic, entry = results[0]
        assert topic == "天气"
        assert entry["id"] == "id1"

    async def test_returns_empty_on_no_match(self, mock_chat: MagicMock) -> None:
        mock_chat.generate.return_value = "3"
        results = await retrieve_full_llm(mock_chat, "无关查询", MEMOS_SAMPLE, 5)
        assert results == []

    async def test_handles_multi_selection(self, mock_chat: MagicMock) -> None:
        mock_chat.generate.return_value = "1#2"
        results = await retrieve_full_llm(mock_chat, "天气和会议", MEMOS_SAMPLE, 5)
        assert {t for t, _ in results} == {"天气", "会议"}

    async def test_returns_empty_on_llm_error(self, mock_chat: MagicMock) -> None:
        mock_chat.generate.side_effect = RuntimeError("fail")
        results = await retrieve_full_llm(mock_chat, "天气", MEMOS_SAMPLE, 5)
        assert results == []


class TestRetrieveHybrid:
    async def test_returns_results_with_embedding(
        self, mock_chat: MagicMock, mock_embedding: MagicMock
    ) -> None:
        mock_chat.generate.return_value = "1"
        results = await retrieve_hybrid(
            mock_chat, mock_embedding, "天气", MEMOS_SAMPLE, 5
        )
        assert len(results) >= 1

    async def test_falls_back_to_keyword_without_embedding(
        self, mock_chat: MagicMock
    ) -> None:
        mock_chat.generate.return_value = "1"
        results = await retrieve_hybrid(mock_chat, None, "天气", MEMOS_SAMPLE, 5)
        assert len(results) >= 1
