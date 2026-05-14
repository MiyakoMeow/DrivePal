"""API 中间件：用户身份提取."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from fastapi import Request
    from starlette.middleware.base import RequestResponseEndpoint
    from starlette.responses import Response


class UserIdentityMiddleware(BaseHTTPMiddleware):
    """从 X-User-Id header 提取用户 ID，注入 request.state.user_id。"""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """提取用户身份并传递至下游处理。"""
        user_id = request.headers.get("X-User-Id", "default")
        request.state.user_id = user_id
        return await call_next(request)
