"""后台任务管理器，封装 asyncio.Task 生命周期。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from .config import MemoryBankConfig

logger = logging.getLogger(__name__)


class BackgroundTaskRunner:
    """管理后台 asyncio.Task 集合，支持优雅关闭。"""

    def __init__(self, config: MemoryBankConfig) -> None:
        """初始化后台任务管理器。

        Args:
            config: MemoryBank 配置。

        """
        self._config = config
        self._tasks: set[asyncio.Task[None]] = set()

    def spawn(self, coro: Coroutine[None, None, None]) -> asyncio.Task[None]:
        """创建后台任务并追踪。失败时日志告警。"""
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._on_task_done)
        return task

    @property
    def pending_count(self) -> int:
        """未完成任务数。"""
        return len(self._tasks)

    def _on_task_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        with contextlib.suppress(asyncio.CancelledError):
            exc = task.exception()
            if exc is not None:
                logger.warning("Background task failed: %s", exc)

    async def shutdown(self) -> None:
        """取消所有未完成任务，等待完成（超时取自 config）。"""
        if not self._tasks:
            return
        for t in self._tasks:
            t.cancel()
        try:
            async with asyncio.timeout(self._config.shutdown_timeout_seconds):
                await asyncio.gather(
                    *self._tasks,
                    return_exceptions=True,
                )
        except TimeoutError:
            logger.warning(
                "Background tasks did not finish within %s seconds during shutdown",
                self._config.shutdown_timeout_seconds,
            )
        for t in self._tasks:
            if not t.done():
                logger.warning("Background task still running after shutdown timeout")
        self._tasks.clear()
