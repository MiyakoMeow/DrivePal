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
    """获取已有调度器，不存在则创建。

    创建置于锁外以释放注册表并发——sched.start() 可能耗时数秒，
    若在锁内将阻塞所有其他用户的 get_or_create / stop / status 操作。
    双重检查锁（line 46）处理竞态：若两请求同时创建，落败方停止重复实例。
    """
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
            existing = _SCHEDULERS[user_id]
        else:
            existing = None
            _SCHEDULERS[user_id] = sched

    # 竞态落败时停止重复实例，stop 在锁外避免阻塞注册表
    if existing is not None:
        try:
            await sched.stop()
        except Exception:
            logger.warning("Failed to stop duplicate scheduler for %s", user_id)
        return existing

    logger.info("ProactiveScheduler started for user: %s", user_id)
    return sched


async def stop_scheduler(user_id: str) -> bool:
    """停止并移除用户调度器。锁内读取 + 身份校验，防替换竞态。"""
    async with _lock:
        sched = _SCHEDULERS.get(user_id)
        if sched is None:
            return False

    try:
        await sched.stop()
    except Exception:
        logger.exception("Error stopping scheduler for user %s", user_id)
        return False

    async with _lock:
        if _SCHEDULERS.get(user_id) is sched:
            _SCHEDULERS.pop(user_id, None)

    logger.info("ProactiveScheduler stopped for user: %s", user_id)
    return True


async def trigger_scheduler(user_id: str) -> bool:
    """手动触发指定用户的调度器执行一次 _tick()。"""
    async with _lock:
        sched = _SCHEDULERS.get(user_id)
    if sched is None:
        return False
    try:
        await sched.trigger_immediate_tick()
    except Exception:
        logger.exception("Error triggering scheduler for user %s", user_id)
        return False
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
