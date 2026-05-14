"""数据查询与管理路由（history、export、delete、experiments）."""

import logging
import shutil

from fastapi import APIRouter, HTTPException

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
    limit: int = 10,
    memory_mode: str = "memory_bank",
    current_user: str = "default",
) -> list[MemoryEventResponse]:
    """查询历史记忆事件."""
    try:
        mode = MemoryMode(memory_mode)
    except ValueError as e:
        raise HTTPException(
            status_code=422, detail=f"Invalid memory_mode: {memory_mode!r}"
        ) from e
    mm = get_memory_module()
    events = await mm.get_history(limit=limit, mode=mode, user_id=current_user)
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
async def export_data(current_user: str = "default") -> ExportDataResponse:
    """导出当前用户全量文本数据."""
    u_dir = user_data_dir(current_user)
    files: dict[str, str] = {}
    if not u_dir.exists():
        return ExportDataResponse(files=files)

    allowed_suffixes = (".jsonl", ".toml", ".json")
    # 排除 memorybank/ 目录：FAISS 二进制索引文件不可作文本导入
    for fpath in u_dir.rglob("*"):
        if "memorybank" in fpath.parts or fpath.suffix not in allowed_suffixes:
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
async def delete_all_data(current_user: str = "default") -> dict[str, bool]:
    """删除当前用户全量数据."""
    u_dir = user_data_dir(current_user)
    if not u_dir.exists():
        return {"success": False}
    try:
        shutil.rmtree(u_dir)
    except OSError as e:
        logger.warning("Failed to delete user data: %s", e)
        return {"success": False}
    return {"success": True}


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
