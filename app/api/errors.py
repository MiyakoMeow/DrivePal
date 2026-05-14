"""API 错误处理：统一错误信封 + 异常体系."""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING

from fastapi import HTTPException
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from fastapi import Request

logger = logging.getLogger(__name__)


class AppErrorCode(StrEnum):
    """应用级错误码."""

    NOT_FOUND = "NOT_FOUND"
    INVALID_INPUT = "INVALID_INPUT"
    STORAGE_ERROR = "STORAGE_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    STREAM_ERROR = "STREAM_ERROR"


class AppError(HTTPException):
    """统一应用异常，携带错误码与 HTTP 状态码.

    响应体格式：{"error": {"code": ..., "message": ...}}
    """

    def __init__(
        self,
        code: AppErrorCode,
        message: str,
        status_code: int = 500,
    ) -> None:
        """初始化应用异常."""
        self.code = code
        self.app_message = message
        super().__init__(status_code=status_code, detail=message)


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    """FastAPI exception handler：AppError → 统一信封 JSON."""
    logger.error(
        "AppError: code=%s status=%d msg=%s", exc.code, exc.status_code, exc.app_message
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code.value, "message": exc.app_message}},
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
        # 通用消息防内部细节泄露至客户端
        raise AppError(
            AppErrorCode.STORAGE_ERROR,
            "Internal storage error",
            503,
        ) from e
    except ValueError as e:
        logger.exception("%s failed", context_msg)
        raise AppError(
            AppErrorCode.INVALID_INPUT,
            "Invalid request data",
            422,
        ) from e
    except Exception as e:
        logger.exception("%s failed", context_msg)
        raise AppError(
            AppErrorCode.INTERNAL_ERROR,
            "Internal server error",
            500,
        ) from e
