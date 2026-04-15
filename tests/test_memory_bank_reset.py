"""reset_forgetting_state 方法测试."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from app.memory.schemas import MemoryEvent
from app.memory.stores.memory_bank import MemoryBankStore

if TYPE_CHECKING:
    from pathlib import Path

EXPECTED_STRENGTH = 5


@pytest.fixture
def store(tmp_path: Path) -> MemoryBankStore:
    """提供空 MemoryBankStore."""
    return MemoryBankStore(tmp_path)


class TestResetForgettingState:
    """reset_forgetting_state 测试."""

    async def test_resets_event_memory_strength_from_zero(
        self,
        store: MemoryBankStore,
    ) -> None:
        """memory_strength=0 应被修正为 1."""
        await store.write(MemoryEvent(content="测试事件"))
        events = await store.events_store.read()
        events[0]["memory_strength"] = 0
        events[0]["forgotten"] = True
        await store.events_store.write(events)

        await store.reset_forgetting_state()

        events = await store.events_store.read()
        assert events[0]["memory_strength"] == 1
        assert "forgotten" not in events[0]

    async def test_resets_event_last_recall_date(
        self,
        store: MemoryBankStore,
    ) -> None:
        """last_recall_date 应被更新为当天."""
        await store.write(MemoryEvent(content="测试事件"))
        events = await store.events_store.read()
        events[0]["last_recall_date"] = "2020-01-01"
        await store.events_store.write(events)

        today = datetime.now(UTC).date().isoformat()
        await store.reset_forgetting_state()

        events = await store.events_store.read()
        assert events[0]["last_recall_date"] == today

    async def test_resets_summaries_memory_strength(
        self,
        store: MemoryBankStore,
    ) -> None:
        """daily_summaries 的 memory_strength=0 应被修正."""
        summaries_data = {
            "daily_summaries": {
                "2025-01-01": {
                    "content": "测试摘要",
                    "memory_strength": 0,
                    "last_recall_date": "2020-01-01",
                },
            },
        }
        await store.summaries_store.write(summaries_data)

        await store.reset_forgetting_state()

        summaries = await store.summaries_store.read()
        entry = summaries["daily_summaries"]["2025-01-01"]
        assert entry["memory_strength"] == 1

    async def test_resets_personality_memory_strength(
        self,
        store: MemoryBankStore,
    ) -> None:
        """daily_personality 的 memory_strength=0 应被修正（A1 修复点）."""
        personality_data = {
            "daily_personality": {
                "2025-01-01": {
                    "content": "用户偏好运动模式",
                    "memory_strength": 0,
                    "last_recall_date": "2020-01-01",
                },
            },
            "overall_personality": "",
        }
        await store.personality_store.write(personality_data)

        await store.reset_forgetting_state()

        personality = await store.personality_store.read()
        entry = personality["daily_personality"]["2025-01-01"]
        assert entry["memory_strength"] == 1

    async def test_resets_personality_last_recall_date(
        self,
        store: MemoryBankStore,
    ) -> None:
        """daily_personality 的 last_recall_date 应被更新为当天（A1 修复点）."""
        personality_data = {
            "daily_personality": {
                "2025-01-01": {
                    "content": "用户偏好",
                    "memory_strength": 1,
                    "last_recall_date": "2020-01-01",
                },
            },
            "overall_personality": "",
        }
        await store.personality_store.write(personality_data)

        today = datetime.now(UTC).date().isoformat()
        await store.reset_forgetting_state()

        personality = await store.personality_store.read()
        entry = personality["daily_personality"]["2025-01-01"]
        assert entry["last_recall_date"] == today

    async def test_does_not_lower_existing_strength(
        self,
        store: MemoryBankStore,
    ) -> None:
        """已有 memory_strength > 1 的条目不应被降低."""
        await store.write(MemoryEvent(content="强记忆事件"))
        events = await store.events_store.read()
        events[0]["memory_strength"] = EXPECTED_STRENGTH
        await store.events_store.write(events)

        await store.reset_forgetting_state()

        events = await store.events_store.read()
        assert events[0]["memory_strength"] == EXPECTED_STRENGTH

    async def test_handles_empty_store(
        self,
        store: MemoryBankStore,
    ) -> None:
        """空存储不应报错."""
        await store.reset_forgetting_state()
