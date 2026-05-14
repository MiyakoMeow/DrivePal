"""v1 sessions 路由."""

from fastapi import APIRouter, Request

from app.agents.conversation import _conversation_manager

router = APIRouter()


@router.post("/{session_id}/close")
async def close_session(session_id: str, request: Request) -> dict[str, bool]:
    """关闭指定会话（校验用户归属）."""
    ok = _conversation_manager.close(session_id, user_id=request.state.user_id)
    return {"success": ok}
