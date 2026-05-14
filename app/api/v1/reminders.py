"""v1 reminders 路由（列表 + 取消）."""

from fastapi import APIRouter, Request

from app.agents.pending import PendingReminderManager
from app.api.schemas import PendingReminderResponse
from app.config import user_data_dir

router = APIRouter()


@router.get("", response_model=list[PendingReminderResponse])
async def get_pending_reminders(request: Request) -> list[PendingReminderResponse]:
    """获取当前用户所有待触发提醒列表."""
    pm = PendingReminderManager(user_data_dir(request.state.user_id))
    pending = await pm.list_pending()
    return [
        PendingReminderResponse(
            id=r["id"],
            event_id=r.get("event_id", ""),
            trigger_type=r.get("trigger_type", ""),
            trigger_text=r.get("trigger_text", ""),
            status=r.get("status", ""),
            created_at=r.get("created_at", ""),
        )
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
