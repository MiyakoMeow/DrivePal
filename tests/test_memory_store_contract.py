"""MemoryStore 接口契约测试 - 验证所有实现满足统一接口."""

from __future__ import annotations

from typing import Any, cast, TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.memory.schemas import FeedbackData, MemoryEvent, SearchResult

if TYPE_CHECKING:
    from app.memory.interfaces import MemoryStore
    from pathlib import Path


def _get_store_params() -> list[str]:
    return ["memory_bank", "memochat"]


class TestMemoryStoreContract:
    """验证所有 MemoryStore 实现满足接口契约."""

    @pytest.fixture(params=_get_store_params())
    async def store(
        self, request: pytest.FixtureRequest, tmp_path: Path
    ) -> "MemoryStore":
        """提供参数化的 MemoryStore 实例."""
        from app.memory.memory import MemoryModule
        from app.memory.types import MemoryMode

        mm = MemoryModule(tmp_path)
        if request.param == "memochat":
            mock_chat = MagicMock()
            mock_chat.generate = AsyncMock(return_value="无相关主题")
            mm._chat_model = mock_chat
        return await mm._get_store(MemoryMode(request.param))

    async def test_write_returns_string_id(self, store: "MemoryStore") -> None:
        """验证 write 返回一个字符串 ID."""
        event_id = await store.write(MemoryEvent(content="test"))
        assert isinstance(event_id, str)
        assert len(event_id) > 0

    async def test_write_then_search_returns_same_event(
        self, store: "MemoryStore"
    ) -> None:
        """验证写入后能在事件存储中找到同一事件."""
        event_id = await store.write(MemoryEvent(content="测试事件"))
        events_store = cast("Any", store).events_store
        events = await events_store.read()
        assert any(e["id"] == event_id for e in events)

    async def test_search_returns_list_of_search_result(
        self, store: "MemoryStore"
    ) -> None:
        """验证 search 返回 SearchResult 列表."""
        await store.write(MemoryEvent(content="测试事件"))
        results = await store.search("测试")
        assert isinstance(results, list)
        assert all(isinstance(r, SearchResult) for r in results)

    async def test_get_history_returns_list_of_memory_event(
        self, store: "MemoryStore"
    ) -> None:
        """验证 get_history 返回 MemoryEvent 列表."""
        await store.write(MemoryEvent(content="事件1"))
        history = await store.get_history(limit=10)
        assert isinstance(history, list)
        assert isinstance(history[0], MemoryEvent)

    async def test_get_history_respects_limit(self, store: "MemoryStore") -> None:
        """验证 get_history 遵守 limit 参数."""
        for i in range(5):
            await store.write(MemoryEvent(content=f"事件{i}"))
        history = await store.get_history(limit=3)
        assert len(history) == 3

    async def test_update_feedback_updates_strategies(
        self, store: "MemoryStore"
    ) -> None:
        """验证 update_feedback 正确更新策略存储."""
        event_id = await store.write(MemoryEvent(content="事件"))
        await store.update_feedback(
            event_id, FeedbackData(action="accept", type="meeting")
        )
        strategies_store = cast("Any", store).strategies_store
        strategies = await strategies_store.read()
        assert "reminder_weights" in strategies
