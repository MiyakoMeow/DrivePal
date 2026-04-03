"""SimulationClock 单例测试."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pytest

from app.simulation.clock import SimulationClock

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture(autouse=True)
def _reset_clock() -> Generator[None]:
    SimulationClock._reset()
    yield
    SimulationClock._reset()


def test_singleton_returns_same_instance() -> None:
    a = SimulationClock()
    b = SimulationClock()
    assert a is b


def test_now_defaults_to_system_time() -> None:
    clock = SimulationClock()
    before = datetime.now(timezone.utc)
    result = clock.now()
    after = datetime.now(timezone.utc)
    assert before <= result <= after


def test_set_time_and_now_returns_simulated() -> None:
    clock = SimulationClock()
    t = datetime(2025, 1, 1, tzinfo=timezone.utc)
    clock.set_time(t)
    assert clock.now() == t


def test_advance_adds_seconds() -> None:
    clock = SimulationClock()
    clock.set_time(datetime(2025, 1, 1, tzinfo=timezone.utc))
    clock.advance(seconds=60)
    assert clock.now() == datetime(2025, 1, 1, 0, 1, tzinfo=timezone.utc)


def test_set_time_scale() -> None:
    clock = SimulationClock()
    clock.set_time_scale(2.0)
    assert clock.time_scale == 2.0


@pytest.mark.asyncio
async def test_start_stop_tick_loop() -> None:
    clock = SimulationClock()
    clock.set_time(datetime(2025, 1, 1, tzinfo=timezone.utc))
    clock.set_time_scale(10.0)
    clock.start()
    try:
        await asyncio.sleep(1.5)
        diff = (clock.now() - datetime(2025, 1, 1, tzinfo=timezone.utc)).total_seconds()
        assert diff >= 10
    finally:
        clock.stop()


@pytest.mark.asyncio
async def test_on_tick_callback() -> None:
    clock = SimulationClock()
    ticks: list[datetime] = []
    clock.on_tick = lambda t: ticks.append(t)
    clock.set_time(datetime(2025, 1, 1, tzinfo=timezone.utc))
    clock.set_time_scale(10.0)
    clock.start()
    try:
        await asyncio.sleep(1.5)
        assert len(ticks) >= 1
        for t in ticks:
            assert t >= datetime(2025, 1, 1, tzinfo=timezone.utc)
    finally:
        clock.stop()
