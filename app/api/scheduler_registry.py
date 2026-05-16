"""Per-user ProactiveScheduler 注册表."""

from __future__ import annotations

import asyncio
import logging

from app.scheduler import ProactiveScheduler

logger = logging.getLogger(__name__)

_SCHEDULERS: dict[str, ProactiveScheduler] = {}
_lock = asyncio.Lock()


async def is_scheduler_running(user_id: str) -> bool:
    """检查用户调度器是否运行中."""
    async with _lock:
        return user_id in _SCHEDULERS


async def get_or_create_scheduler(user_id: str) -> ProactiveScheduler | None:
    """获取已有调度器，不存在则创建。创建在锁外，防长时间持锁。"""
    async with _lock:
        if user_id in _SCHEDULERS:
            return _SCHEDULERS[user_id]

    try:
        from app.agents.workflow import AgentWorkflow
        from app.api.v1.ws_manager import ws_manager as ws_mgr
        from app.memory.singleton import get_memory_module

        wf = AgentWorkflow(current_user=user_id)
        mm = get_memory_module()
        sched = ProactiveScheduler(
            workflow=wf,
            memory_module=mm,
            user_id=user_id,
            ws_manager=ws_mgr,
        )
        await sched.start()
    except Exception as e:
        logger.warning("Failed to start scheduler for %s: %s", user_id, e)
        return None

    async with _lock:
        if user_id in _SCHEDULERS:
            try:
                await sched.stop()
            except Exception:
                logger.warning("Failed to stop duplicate scheduler for %s", user_id)
            return _SCHEDULERS[user_id]
        _SCHEDULERS[user_id] = sched

    logger.info("ProactiveScheduler started for user: %s", user_id)
    return sched


async def stop_scheduler(user_id: str) -> bool:
    """停止并移除用户调度器。先停后移，防 stop() 抛异常致丢失。"""
    sched = _SCHEDULERS.get(user_id)
    if sched is None:
        return False

    try:
        await sched.stop()
    except Exception:
        logger.exception("Error stopping scheduler for user %s", user_id)
        return False

    async with _lock:
        _SCHEDULERS.pop(user_id, None)

    logger.info("ProactiveScheduler stopped for user: %s", user_id)
    return True


async def stop_all_schedulers() -> None:
    """停止所有调度器（lifespan 关闭时调用）。单失败不阻塞其余。"""
    async with _lock:
        uids = list(_SCHEDULERS.keys())

    results = await asyncio.gather(
        *(stop_scheduler(uid) for uid in uids),
        return_exceptions=True,
    )
    for uid, result in zip(uids, results, strict=True):
        if isinstance(result, Exception):
            logger.exception("Error stopping scheduler %s", uid)
