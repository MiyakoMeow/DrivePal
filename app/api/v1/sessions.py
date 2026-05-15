"""v1 sessions 路由."""

import logging

from fastapi import APIRouter, Request

from app.agents.conversation import _conversation_manager
from app.api.errors import AppError, AppErrorCode

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/{session_id}/close")
async def close_session(session_id: str, request: Request) -> dict[str, bool]:
    """关闭指定会话（校验用户归属）."""
    try:
        ok = _conversation_manager.close(session_id, user_id=request.state.user_id)
    except Exception:
        logger.exception("close_session failed")
        raise AppError(AppErrorCode.INTERNAL_ERROR, "Failed to close session") from None
    return {"success": ok}
