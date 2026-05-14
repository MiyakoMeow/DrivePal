"""v1 data 路由（history、export、delete、experiments）."""

import logging
import shutil
from typing import Literal

from fastapi import APIRouter, Request

from app.api.errors import safe_memory_call
from app.api.schemas import (
    ExperimentResultResponse,
    ExperimentResultsResponse,
    ExportDataResponse,
    MemoryEventResponse,
)
from app.config import user_data_dir
from app.memory.singleton import get_memory_module
from app.memory.types import MemoryMode
from app.storage.experiment_store import read_benchmark

logger = logging.getLogger(__name__)
router = APIRouter()


def _safe_float(metrics: dict, key: str) -> float:
    """安全获取 metric 值."""
    try:
        return float(metrics.get(key, 0.0))
    except ValueError, TypeError:
        return 0.0


@router.get("/history", response_model=list[MemoryEventResponse])
async def get_history(
    request: Request,
    limit: int = 10,
) -> list[MemoryEventResponse]:
    """查询历史记忆事件."""
    user_id = request.state.user_id
    mm = get_memory_module()
    events = await safe_memory_call(
        mm.get_history(limit=limit, mode=MemoryMode.MEMORY_BANK, user_id=user_id),
        "get_history",
    )
    return [
        MemoryEventResponse(
            id=e.id,
            content=e.content,
            type=e.type,
            description=e.description,
            created_at=e.created_at,
        )
        for e in events
    ]


@router.get("/export", response_model=ExportDataResponse)
async def export_data(
    request: Request,
    export_type: Literal["events", "settings", "all"] = "all",
) -> ExportDataResponse:
    """导出当前用户文本数据，按类型过滤."""
    u_dir = user_data_dir(request.state.user_id)
    files: dict[str, str] = {}
    if not u_dir.exists():
        return ExportDataResponse(files=files)

    allowed = _allowed_suffixes(export_type)
    for fpath in u_dir.rglob("*"):
        if "memorybank" in fpath.parts or fpath.suffix not in allowed:
            continue
        if fpath.is_file():
            try:
                content = fpath.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            rel = str(fpath.relative_to(u_dir))
            files[rel] = content
    return ExportDataResponse(files=files)


@router.delete("/data")
async def delete_all_data(request: Request) -> dict[str, bool]:
    """删除当前用户全量数据."""
    u_dir = user_data_dir(request.state.user_id)
    if not u_dir.exists():
        return {"success": False}
    try:
        shutil.rmtree(u_dir)
    except OSError as e:
        logger.warning("Failed to delete user data: %s", e)
        return {"success": False}
    return {"success": True}


def _allowed_suffixes(export_type: str) -> tuple[str, ...]:
    if export_type == "events":
        return (".jsonl",)
    if export_type == "settings":
        return (".toml",)
    return (".jsonl", ".toml", ".json")


@router.get("/experiments", response_model=ExperimentResultsResponse)
async def get_experiment_results() -> ExperimentResultsResponse:
    """查询五策略实验结果对比."""
    try:
        data = read_benchmark()
    except (OSError, ValueError) as e:
        logger.warning("Failed to read experiment benchmark: %s", e)
        data = {}
    strategies = []
    for name, metrics in data.get("strategies", {}).items():
        try:
            strategies.append(
                ExperimentResultResponse(
                    strategy=name,
                    exact_match=_safe_float(metrics, "exact_match"),
                    field_f1=_safe_float(metrics, "field_f1"),
                    value_f1=_safe_float(metrics, "value_f1"),
                )
            )
        except (ValueError, TypeError) as e:
            logger.warning("Skipping invalid strategy %s: %s", name, e)
    return ExperimentResultsResponse(strategies=strategies)
