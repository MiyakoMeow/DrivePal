"""REST API 错误处理工具."""

import logging
from typing import TYPE_CHECKING

from fastapi import HTTPException

if TYPE_CHECKING:
    from collections.abc import Awaitable

logger = logging.getLogger(__name__)


async def safe_memory_call[T](
    coro: Awaitable[T],
    context_msg: str,
) -> T:
    """执行记忆系统调用，异常统一转为 HTTPException.

    OSError → 503（存储服务不可用）
    ValueError → 422（数据校验失败）
    其余 → 500（内部错误）
    """
    try:
        return await coro
    except OSError as e:
        logger.exception("%s failed", context_msg)
        raise HTTPException(status_code=503, detail="Internal storage error") from e
    except ValueError as e:
        logger.exception("%s failed", context_msg)
        raise HTTPException(
            status_code=422, detail=f"Invalid data in {context_msg}"
        ) from e
    except Exception as e:
        logger.exception("%s failed", context_msg)
        raise HTTPException(status_code=500, detail="Internal server error") from e
