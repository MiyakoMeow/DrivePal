"""模拟时钟单例，支持时间缩放和回调."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import Callable, cast

logger = logging.getLogger(__name__)

_instance: SimulationClock | None = None
_created: bool = False


class SimulationClock:
    """模拟时钟单例，支持时间缩放和回调."""

    def __new__(cls) -> SimulationClock:
        """创建或返回单例实例."""
        global _instance, _created
        if not _created:
            _instance = super().__new__(cls)
            _created = True
        return cast("SimulationClock", _instance)

    def __init__(self) -> None:
        """初始化时钟状态（仅首次创建时执行）."""
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self._simulated_time: datetime | None = None
        self._time_scale: float = 1.0
        self._running: bool = False
        self._task: asyncio.Task[None] | None = None
        self._on_tick: Callable[[datetime], None] | None = None
        self._last_wall: float | None = None

    @property
    def time_scale(self) -> float:
        """获取当前时间缩放倍率."""
        return self._time_scale

    def now(self) -> datetime:
        """获取当前时间（模拟时间或系统时间）."""
        if self._simulated_time is not None:
            return self._simulated_time
        return datetime.now(timezone.utc)

    def set_time(self, t: datetime) -> None:
        """设置模拟时间基准点."""
        self._simulated_time = t
        self._last_wall = time.monotonic()

    def advance(self, seconds: float = 1.0) -> None:
        """向前推进模拟时间."""
        if self._simulated_time is not None:
            self._simulated_time += timedelta(seconds=seconds)

    def set_time_scale(self, scale: float) -> None:
        """设置时间缩放倍率."""
        self._time_scale = scale

    @property
    def on_tick(self) -> Callable[[datetime], None] | None:
        """获取每秒回调函数."""
        return self._on_tick

    @on_tick.setter
    def on_tick(self, callback: Callable[[datetime], None] | None) -> None:
        self._on_tick = callback

    def start(self) -> None:
        """启动后台 tick 任务."""
        if self._running:
            return
        self._running = True
        self._last_wall = time.monotonic()
        self._task = asyncio.create_task(self._tick_loop())

    def stop(self) -> None:
        """停止后台 tick 任务."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            with suppress(asyncio.CancelledError, RuntimeError):
                asyncio.get_event_loop().run_until_complete(self._task)
        self._task = None

    async def _tick_loop(self) -> None:
        while self._running:
            await asyncio.sleep(1.0)
            now_wall = time.monotonic()
            if self._last_wall is not None and self._simulated_time is not None:
                elapsed = now_wall - self._last_wall
                self.advance(seconds=elapsed * self._time_scale)
                if self._on_tick is not None:
                    try:
                        self._on_tick(self._simulated_time)
                    except Exception:
                        logger.exception("Tick callback error")
            self._last_wall = now_wall

    @classmethod
    def _reset(cls) -> None:
        global _instance, _created
        _instance = None
        _created = False
