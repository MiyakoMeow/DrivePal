"""BackgroundTaskRunner 单元测试。"""

import asyncio

import pytest

from app.memory.memory_bank.bg_tasks import BackgroundTaskRunner
from app.memory.memory_bank.config import MemoryBankConfig


@pytest.mark.asyncio
async def test_spawn_and_shutdown():
    """Given 后台任务运行器，When 提交协程后 shutdown，Then 任务被取消。"""
    config = MemoryBankConfig()
    runner = BackgroundTaskRunner(config)
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def work():
        started.set()
        try:
            await asyncio.sleep(999)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    runner.spawn(work())
    await asyncio.wait_for(started.wait(), timeout=5)
    await runner.shutdown()
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_shutdown_no_tasks():
    """Given 无后台任务，When shutdown，Then 正常完成不报错。"""
    config = MemoryBankConfig()
    runner = BackgroundTaskRunner(config)
    await runner.shutdown()


@pytest.mark.asyncio
async def test_failed_task_warning(caplog):
    """Given 后台任务抛异常，When 任务完成，Then 日志警告。"""
    config = MemoryBankConfig()
    runner = BackgroundTaskRunner(config)

    async def fail():
        msg = "boom"
        raise RuntimeError(msg)

    runner.spawn(fail())
    await asyncio.sleep(0.1)
    assert "Background task failed" in caplog.text
