"""MemoChatStore 测试."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.memory.schemas import FeedbackData, MemoryEvent
from app.memory.stores.memochat.store import MemoChatStore
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def mock_chat() -> MagicMock:
    chat = MagicMock()
    chat.generate = AsyncMock(return_value="测试摘要")
    return chat


@pytest.fixture
def store(tmp_path: Path, mock_chat: MagicMock) -> MemoChatStore:
    return MemoChatStore(tmp_path, chat_model=mock_chat)


class TestStoreAttributes:
    def test_store_name(self, store: MemoChatStore) -> None:
        assert store.store_name == "memochat"

    def test_requires_embedding_false(self, store: MemoChatStore) -> None:
        assert store.requires_embedding is False

    def test_requires_chat_true(self, store: MemoChatStore) -> None:
        assert store.requires_chat is True

    def test_supports_interaction_true(self, store: MemoChatStore) -> None:
        assert store.supports_interaction is True


class TestWrite:
    async def test_write_returns_string_id(self, store: MemoChatStore) -> None:
        event_id = await store.write(MemoryEvent(content="测试内容", type="测试主题"))
        assert isinstance(event_id, str)
        assert len(event_id) > 0

    async def test_write_creates_memo_entry(self, store: MemoChatStore) -> None:
        await store.write(MemoryEvent(content="明天开会", type="会议"))
        memos = await store._engine.read_memos()
        assert "会议" in memos
        assert any("明天开会" in e.get("summary", "") for e in memos["会议"])


class TestGetHistory:
    async def test_get_history_returns_events(self, store: MemoChatStore) -> None:
        await store.write(MemoryEvent(content="事件1", type="主题1"))
        await store.write(MemoryEvent(content="事件2", type="主题2"))
        history = await store.get_history(limit=10)
        assert len(history) >= 2
        assert all(isinstance(e, MemoryEvent) for e in history)

    async def test_get_history_respects_limit(self, store: MemoChatStore) -> None:
        for i in range(5):
            await store.write(MemoryEvent(content=f"事件{i}", type=f"主题{i}"))
        history = await store.get_history(limit=3)
        assert len(history) == 3


class TestUpdateFeedback:
    async def test_update_feedback_records(self, store: MemoChatStore) -> None:
        event_id = await store.write(MemoryEvent(content="测试"))
        await store.update_feedback(
            event_id, FeedbackData(action="accept", type="meeting")
        )
        strategies = await store._feedback._strategies_store.read()
        assert "reminder_weights" in strategies


class TestWriteInteraction:
    async def test_write_interaction_stores_record(self, store: MemoChatStore) -> None:
        iid = await store.write_interaction("提醒我开会", "好的已记录")
        interactions = await store._engine.read_interactions()
        assert any(i["id"] == iid for i in interactions)
