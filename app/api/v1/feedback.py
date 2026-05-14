"""v1 feedback 路由."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Request

from app.agents.outputs import InterruptLevel, MultiFormatContent, OutputChannel
from app.agents.pending import PendingReminderManager
from app.api.errors import AppError, AppErrorCode, safe_memory_call
from app.api.schemas import FeedbackRequest, FeedbackResponse
from app.config import user_data_dir
from app.memory.schemas import FeedbackData
from app.memory.singleton import get_memory_module
from app.memory.types import MemoryMode
from app.storage.feedback_log import aggregate_weights, append_feedback
from app.storage.toml_store import TOMLStore

logger = logging.getLogger(__name__)
router = APIRouter()


async def _handle_memory_feedback(
    req: FeedbackRequest,
    user_id: str,
    memory_action: Literal["accept", "ignore"],
) -> None:
    """accept/ignore/modify 的 memory 反馈路径."""
    mm = get_memory_module()
    mode = MemoryMode.MEMORY_BANK

    actual_type = await safe_memory_call(
        mm.get_event_type(req.event_id, mode=mode),
        "feedback(get_event_type)",
    )
    if actual_type is None:
        raise AppError(
            AppErrorCode.NOT_FOUND,
            f"Event not found: {req.event_id!r}",
            404,
        )

    feedback = FeedbackData(
        action=memory_action,
        type=actual_type,
        modified_content=req.modified_content,
    )
    await safe_memory_call(
        mm.update_feedback(req.event_id, feedback, mode=mode, user_id=user_id),
        "feedback(update_feedback)",
    )

    user_dir = user_data_dir(user_id)
    await append_feedback(user_dir, req.event_id, req.action, actual_type)

    aggregated = await aggregate_weights(user_dir)
    strategy_store = TOMLStore(
        user_dir=user_dir,
        filename="strategies.toml",
        default_factory=dict,
    )
    await strategy_store.merge_dict_key("reminder_weights", aggregated)


async def _handle_snooze(req: FeedbackRequest, user_id: str) -> None:
    """Snooze 路径：创建延后提醒."""
    pm = PendingReminderManager(user_data_dir(user_id))
    target_time = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    content = MultiFormatContent(
        speakable_text="延后提醒",
        display_text="延后提醒",
        detailed=req.modified_content or "",
        channel=OutputChannel.AUDIO,
        interrupt_level=InterruptLevel.NORMAL,
    )
    await pm.add(
        content=content,
        trigger_type="time",
        trigger_target={"time": target_time},
        event_id=req.event_id,
        trigger_text="延后 5 分钟",
    )


@router.post("", response_model=FeedbackResponse)
async def submit_feedback(req: FeedbackRequest, request: Request) -> FeedbackResponse:
    """提交用户反馈."""
    user_id = request.state.user_id

    if req.action == "snooze":
        await _handle_snooze(req, user_id)
    else:
        # memory 模块仅识别 accept/ignore，modify 走 accept 反馈路径
        memory_action = "accept" if req.action == "modify" else req.action
        await _handle_memory_feedback(req, user_id, memory_action)

    return FeedbackResponse(status="success")
