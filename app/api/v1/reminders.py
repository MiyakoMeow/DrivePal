"""v1 reminders 路由（列表 + 取消 + 轮询触发 + WS 广播）."""

import logging

from fastapi import APIRouter, Request

from app.agents.pending import PendingReminderManager
from app.api.schemas import (
    PollRemindersRequest,
    PollRemindersResponse,
    TriggeredReminderResponse,
)
from app.api.v1.ws_manager import ws_manager
from app.config import user_data_dir

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("")
async def get_pending_reminders(request: Request) -> list[dict]:
    """获取当前用户所有待触发提醒列表."""
    pm = PendingReminderManager(user_data_dir(request.state.user_id))
    pending = await pm.list_pending()
    return [
        {
            "id": r["id"],
            "event_id": r.get("event_id", ""),
            "trigger_type": r.get("trigger_type", ""),
            "trigger_text": r.get("trigger_text", ""),
            "status": r.get("status", ""),
            "created_at": r.get("created_at", ""),
        }
        for r in pending
    ]


@router.delete("/{reminder_id}")
async def cancel_pending_reminder(
    reminder_id: str, request: Request
) -> dict[str, bool]:
    """取消指定 ID 的待触发提醒."""
    pm = PendingReminderManager(user_data_dir(request.state.user_id))
    await pm.cancel(reminder_id)
    return {"success": True}


@router.post("/poll", response_model=PollRemindersResponse)
async def poll_reminders(
    request: Request, body: PollRemindersRequest
) -> PollRemindersResponse:
    """轮询触发条件，满足的提醒经 WS 广播给前端."""
    user_id = request.state.user_id
    pm = PendingReminderManager(user_data_dir(user_id))

    context = body.context.model_dump() if body.context else {}
    triggered = await pm.poll(context)

    results = []
    for r in triggered:
        # WS 广播触发的提醒
        await ws_manager.broadcast(user_id, {"type": "reminder_triggered", "data": r})
        results.append(
            TriggeredReminderResponse(
                id=r["id"],
                event_id=r.get("event_id", ""),
                content=r.get("content", {}),
                triggered_at=r.get("created_at", ""),
            )
        )

    return PollRemindersResponse(triggered=results)
