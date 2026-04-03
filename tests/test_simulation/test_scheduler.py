from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_storage():
    with patch("app.simulation.scheduler.broadcast_reminder", new_callable=AsyncMock):
        storage = MagicMock()
        storage.read_events = AsyncMock(
            return_value=[
                {
                    "id": "evt1",
                    "content": "明天开会",
                    "remind_at": "2025-06-01T09:00:00+00:00",
                },
                {"id": "evt2", "content": "买东西", "remind_at": None},
            ]
        )
        yield storage


@pytest.fixture
def mock_clock():
    clock = MagicMock()
    clock.now.return_value = datetime(2025, 6, 1, 8, 55, 0, tzinfo=timezone.utc)
    return clock


@pytest.fixture
def mock_state():
    state = MagicMock()
    state.get_context.return_value.model_dump.return_value = {
        "driving_mode": "normal",
        "weather": "clear",
    }
    return state


@pytest.fixture
def scheduler(mock_clock, mock_state, mock_storage):
    from app.simulation.scheduler import EventScheduler

    return EventScheduler(
        clock=mock_clock,
        state=mock_state,
        event_storage=mock_storage,
        workflow_factory=None,
        poll_interval=0.1,
    )


@pytest.mark.asyncio
async def test_scheduler_no_trigger_before_time(scheduler, mock_clock, mock_storage):
    mock_clock.now.return_value = datetime(2025, 6, 1, 8, 55, 0, tzinfo=timezone.utc)
    await scheduler.tick()

    assert "evt1" not in scheduler._notified


@pytest.mark.asyncio
async def test_scheduler_triggers_on_remind_at(scheduler, mock_clock, mock_storage):
    mock_clock.now.return_value = datetime(2025, 6, 1, 9, 0, 1, tzinfo=timezone.utc)
    await scheduler.tick()

    assert "evt1" in scheduler._notified


@pytest.mark.asyncio
async def test_scheduler_dedup(scheduler, mock_clock, mock_storage):
    mock_clock.now.return_value = datetime(2025, 6, 1, 9, 0, 1, tzinfo=timezone.utc)
    await scheduler.tick()
    await scheduler.tick()

    assert "evt1" in scheduler._notified
    assert mock_storage.read_events.call_count == 2


@pytest.mark.asyncio
async def test_scheduler_skip_no_remind_at(scheduler, mock_clock, mock_storage):
    mock_clock.now.return_value = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
    await scheduler.tick()

    assert "evt2" not in scheduler._notified
