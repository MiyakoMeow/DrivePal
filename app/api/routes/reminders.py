"""待触发提醒路由."""

from datetime import UTC, datetime

from fastapi import APIRouter

from app.agents.pending import PendingReminderManager
from app.api.schemas import (
    PendingReminderResponse,
    PollRemindersRequest,
    PollRemindersResponse,
    TriggeredReminderResponse,
)
from app.config import user_data_dir

router = APIRouter()


@router.post("/poll", response_model=PollRemindersResponse)
async def poll_pending_reminders(req: PollRemindersRequest) -> PollRemindersResponse:
    """车机端轮询待触发提醒."""
    pm = PendingReminderManager(user_data_dir(req.current_user))
    ctx = req.context.model_dump() if req.context else {}
    triggered = await pm.poll(ctx)
    return PollRemindersResponse(
        triggered=[
            TriggeredReminderResponse(
                id=r["id"],
                event_id=r.get("event_id", ""),
                content=r.get("content", {}),
                triggered_at=datetime.now(UTC).isoformat(),
            )
            for r in triggered
        ]
    )


@router.delete("/{reminder_id}")
async def cancel_pending_reminder(
    reminder_id: str,
    current_user: str = "default",
) -> dict[str, bool]:
    """取消指定 ID 的待触发提醒."""
    pm = PendingReminderManager(user_data_dir(current_user))
    await pm.cancel(reminder_id)
    return {"success": True}


@router.get("", response_model=list[PendingReminderResponse])
async def get_pending_reminders(
    current_user: str = "default",
) -> list[PendingReminderResponse]:
    """获取当前用户所有待触发提醒列表."""
    pm = PendingReminderManager(user_data_dir(current_user))
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
