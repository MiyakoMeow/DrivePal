"""API 错误处理：统一错误信封 + 异常体系."""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.exceptions import AppError as BaseAppError
from app.memory.exceptions import FatalError, TransientError
from app.tools.executor import ToolExecutionError

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


_CODE_TO_HTTP: dict[AppErrorCode, int] = {
    AppErrorCode.NOT_FOUND: 404,
    AppErrorCode.INVALID_INPUT: 422,
    AppErrorCode.STORAGE_ERROR: 503,
    AppErrorCode.INTERNAL_ERROR: 500,
}


class AppError(BaseAppError, HTTPException):
    """API 异常——同时是 BaseAppError 和 HTTPException.

    isinstance(err, BaseAppError) → True（safe_call 可 catch）
    isinstance(err, HTTPException) → True（FastAPI exception handler 可 catch）
    """

    def __init__(
        self,
        code: AppErrorCode,
        message: str,
        status_code: int | None = None,
    ) -> None:
        self.app_message = message
        self.code = code.value
        self.message = message
        resolved = (
            status_code if status_code is not None else _CODE_TO_HTTP.get(code, 500)
        )
        Exception.__init__(self, message)
        HTTPException.__init__(self, status_code=resolved, detail=message)


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
        content={"error": {"code": exc.code, "message": exc.app_message}},
    )


async def validation_error_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Pydantic 校验失败 → 统一信封."""
    details = "; ".join(str(e) for e in exc.errors())
    return JSONResponse(
        status_code=422,
        content={
            "error": {"code": AppErrorCode.INVALID_INPUT.value, "message": details}
        },
    )


async def safe_call[T](
    coro: Awaitable[T],
    context_msg: str,
) -> T:
    """执行异步调用，异常统一转为 AppError（HTTP 子类）。

    BaseAppError 子类（含 API AppError）→ 直接 raise
    TransientError → 503
    FatalError → 500
    ToolExecutionError → 500
    ValueError → 422
    OSError → 503
    其余 → 500
    """
    try:
        return await coro
    except BaseAppError:
        raise
    except TransientError as e:
        logger.exception("%s: transient error", context_msg)
        raise AppError(
            AppErrorCode.STORAGE_ERROR, "Service temporarily unavailable"
        ) from e
    except FatalError as e:
        logger.exception("%s: fatal error", context_msg)
        raise AppError(AppErrorCode.INTERNAL_ERROR, "Internal storage error") from e
    except ToolExecutionError as e:
        logger.exception("%s: tool error", context_msg)
        raise AppError(AppErrorCode.INTERNAL_ERROR, "Tool execution failed") from e
    except OSError as e:
        logger.exception("%s: IO error", context_msg)
        raise AppError(
            AppErrorCode.STORAGE_ERROR, "Service temporarily unavailable"
        ) from e
    except ValueError as e:
        logger.exception("%s: validation error", context_msg)
        raise AppError(AppErrorCode.INVALID_INPUT, "Invalid request data") from e
    except Exception as e:
        logger.exception("%s: unexpected error", context_msg)
        raise AppError(AppErrorCode.INTERNAL_ERROR, "Internal server error") from e


safe_memory_call = safe_call
