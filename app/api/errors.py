"""API 错误处理：统一错误信封 + 异常体系."""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
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


_CODE_TO_HTTP: dict[AppErrorCode, int] = {
    AppErrorCode.NOT_FOUND: 404,
    AppErrorCode.INVALID_INPUT: 422,
    AppErrorCode.STORAGE_ERROR: 503,
    AppErrorCode.INTERNAL_ERROR: 500,
    AppErrorCode.STREAM_ERROR: 500,
}


class AppError(HTTPException):
    """统一应用异常，携带错误码与 HTTP 状态码.

    响应体格式：{"error": {"code": ..., "message": ...}}
    status_code 由 code 自动派生，无需调用者指定。
    """

    def __init__(
        self,
        code: AppErrorCode,
        message: str,
        status_code: int | None = None,
    ) -> None:
        """初始化应用异常."""
        self.code = code
        self.app_message = message
        resolved = (
            status_code if status_code is not None else _CODE_TO_HTTP.get(code, 500)
        )
        super().__init__(status_code=resolved, detail=message)


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    """FastAPI exception handler：AppError → 统一信封 JSON."""
    logger.warning(
        "AppError: code=%s status=%d msg=%s",
        exc.code,
        exc.status_code,
        exc.app_message,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code.value, "message": exc.app_message}},
    )


async def validation_error_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Pydantic 校验失败 → 统一信封."""
    details = "; ".join(str(e) for e in exc.errors())
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "INVALID_INPUT", "message": details}},
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
    except AppError:
        raise
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
