"""v1 presets 路由."""

from typing import Any

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, Any]:
    """健康检查."""
    return {"status": "ok"}
