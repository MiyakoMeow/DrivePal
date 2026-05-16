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
    """获取已有调度器，不存在则创建."""
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
        _SCHEDULERS[user_id] = sched
    logger.info("ProactiveScheduler started for user: %s", user_id)
    return sched


async def stop_scheduler(user_id: str) -> bool:
    """停止并移除用户调度器."""
    async with _lock:
        sched = _SCHEDULERS.pop(user_id, None)
    if sched is None:
        return False
    try:
        await sched.stop()
    except Exception:
        logger.exception("Error stopping scheduler for user %s", user_id)
    else:
        logger.info("ProactiveScheduler stopped for user: %s", user_id)
    return True


async def stop_all_schedulers() -> None:
    """停止所有调度器（lifespan 关闭时调用）."""
    async with _lock:
        uids = list(_SCHEDULERS.keys())
    for uid in uids:
        await stop_scheduler(uid)
