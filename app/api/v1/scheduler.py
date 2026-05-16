"""调度器控制路由：per-user ProactiveScheduler 启停."""

import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.api.errors import AppError, AppErrorCode
from app.api.scheduler_registry import (
    get_or_create_scheduler,
    is_scheduler_running,
    stop_scheduler,
    trigger_scheduler,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class SchedulerStartResponse(BaseModel):
    """调度器启动响应."""

    status: str
    user_id: str


class SchedulerStopResponse(BaseModel):
    """调度器停止响应."""

    status: str
    user_id: str


class SchedulerTriggerResponse(BaseModel):
    """调度器手动触发响应."""

    status: str
    user_id: str


class SchedulerStatusResponse(BaseModel):
    """调度器状态响应."""

    user_id: str
    running: bool


@router.post("/start", response_model=SchedulerStartResponse)
async def start_scheduler(request: Request) -> SchedulerStartResponse:
    """启动当前用户的主动调度器."""
    user_id: str = request.state.user_id
    sched = await get_or_create_scheduler(user_id)
    if sched is None:
        raise AppError(
            code=AppErrorCode.SERVICE_UNAVAILABLE,
            message="Failed to start scheduler",
        )
    return SchedulerStartResponse(status="started", user_id=user_id)


@router.post("/stop", response_model=SchedulerStopResponse)
async def stop_scheduler_route(request: Request) -> SchedulerStopResponse:
    """停止当前用户的主动调度器."""
    user_id: str = request.state.user_id
    ok = await stop_scheduler(user_id)
    return SchedulerStopResponse(
        status="stopped" if ok else "not_found", user_id=user_id
    )


@router.post("/trigger", response_model=SchedulerTriggerResponse)
async def trigger_scheduler_route(request: Request) -> SchedulerTriggerResponse:
    """手动触发当前用户的调度器立即执行一次 tick。"""
    user_id: str = request.state.user_id
    ok = await trigger_scheduler(user_id)
    if not ok:
        raise AppError(
            code=AppErrorCode.SERVICE_UNAVAILABLE,
            message="Scheduler not running for user",
        )
    return SchedulerTriggerResponse(status="triggered", user_id=user_id)


@router.get("/status", response_model=SchedulerStatusResponse)
async def scheduler_status(request: Request) -> SchedulerStatusResponse:
    """查询当前用户调度器运行状态."""
    user_id: str = request.state.user_id
    return SchedulerStatusResponse(
        user_id=user_id, running=await is_scheduler_running(user_id)
    )
