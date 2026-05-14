"""反馈路由."""

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException

from app.api.errors import safe_memory_call
from app.api.schemas import FeedbackRequest, FeedbackResponse
from app.config import user_data_dir
from app.memory.schemas import FeedbackData
from app.memory.singleton import get_memory_module
from app.memory.types import MemoryMode
from app.storage.feedback_log import aggregate_weights, append_feedback
from app.storage.toml_store import TOMLStore

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("", response_model=FeedbackResponse)
async def submit_feedback(req: FeedbackRequest) -> FeedbackResponse:
    """提交用户反馈."""
    try:
        mm = get_memory_module()
    except Exception as e:
        logger.exception("submitFeedback failed (get_memory_module)")
        raise HTTPException(status_code=500, detail="Internal server error") from e

    safe_action: Literal["accept", "ignore"] = req.action
    mode = MemoryMode.MEMORY_BANK

    actual_type = await safe_memory_call(
        mm.get_event_type(req.event_id, mode=mode),
        "submitFeedback(get_event_type)",
    )

    if actual_type is None:
        raise HTTPException(
            status_code=404, detail=f"Event not found: {req.event_id!r}"
        )

    feedback = FeedbackData(
        action=safe_action,
        type=actual_type,
        modified_content=req.modified_content,
    )
    await safe_memory_call(
        mm.update_feedback(
            req.event_id,
            feedback,
            mode=mode,
            user_id=req.current_user,
        ),
        "submitFeedback(update_feedback)",
    )

    # 追加写反馈日志（append-only，无并发冲突）
    user_dir = user_data_dir(req.current_user)
    await append_feedback(user_dir, req.event_id, safe_action, actual_type)

    # 从日志聚合权重，与既有 weights 合并（日志有记录的类型覆盖，无记录的类型保留）
    aggregated = await aggregate_weights(user_dir)
    strategy_store = TOMLStore(
        user_dir=user_dir,
        filename="strategies.toml",
        default_factory=dict,
    )
    current = await strategy_store.read()
    existing_weights = current.get("reminder_weights", {})
    if isinstance(existing_weights, dict):
        existing_weights.update(aggregated)
        merged = existing_weights
    else:
        merged = aggregated
    await strategy_store.update("reminder_weights", merged)

    return FeedbackResponse(status="success")
