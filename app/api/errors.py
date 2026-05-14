"""API 错误处理：统一错误信封 + 异常体系."""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from fastapi import Request

logger = logging.getLogger(__name__)


class AppErrorCode(StrEnum):
    """应用级错误码."""

    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"
    INVALID_REQUEST = "INVALID_REQUEST"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AppError(Exception):
    """统一应用异常，携带错误码与 HTTP 状态码."""

    def __init__(
        self,
        code: AppErrorCode,
        status_code: int,
        detail: str,
    ) -> None:
        """初始化应用异常."""
        self.code = code
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    """FastAPI exception handler：AppError → 统一信封 JSON."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code.value, "detail": exc.detail}},
    )


async def safe_memory_call[T](
    coro: Awaitable[T],
    context_msg: str,
) -> T:
    """执行记忆系统调用，异常统一转为 AppError.

    OSError → 503（存储服务不可用）
    ValueError → 422（数据校验失败）
    其余 → 500（内部错误）
    """
    try:
        return await coro
    except OSError as e:
        logger.exception("%s failed", context_msg)
        raise AppError(
            AppErrorCode.STORAGE_UNAVAILABLE,
            503,
            "Internal storage error",
        ) from e
    except ValueError as e:
        logger.exception("%s failed", context_msg)
        raise AppError(
            AppErrorCode.INVALID_REQUEST,
            422,
            "Invalid request data",
        ) from e
    except Exception as e:
        logger.exception("%s failed", context_msg)
        raise AppError(
            AppErrorCode.INTERNAL_ERROR,
            500,
            "Internal server error",
        ) from e
