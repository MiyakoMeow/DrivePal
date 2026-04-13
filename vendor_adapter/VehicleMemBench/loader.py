"""QA/历史/prep 数据加载."""

import asyncio
import json
import logging
from typing import Any

import aiofiles

from vendor_adapter.VehicleMemBench import BenchMemoryMode  # noqa: TC001
from vendor_adapter.VehicleMemBench.paths import (
    BENCHMARK_DIR,
)
from vendor_adapter.VehicleMemBench.paths import (
    prep_path as _prep_path,
)

logger = logging.getLogger(__name__)


def _is_prep_free(mtype: BenchMemoryMode) -> bool:
    from vendor_adapter.VehicleMemBench.strategies import STRATEGIES  # noqa: PLC0415

    s = STRATEGIES[mtype]
    return not s.needs_history() and not s.needs_agent_for_prep()


async def load_qa(file_num: int) -> dict[str, Any] | None:
    """加载 QA JSON 数据."""
    path = BENCHMARK_DIR / "qa_data" / f"qa_{file_num}.json"
    async with aiofiles.open(path, encoding="utf-8") as f:
        parsed = json.loads(await f.read())
        if not isinstance(parsed, dict):
            logger.warning(
                "[warn] qa file %d root is not a dict, got %s",
                file_num,
                type(parsed).__name__,
            )
            return None
        return parsed


async def load_history(file_num: int) -> str:
    """加载历史文本."""
    path = BENCHMARK_DIR / "history" / f"history_{file_num}.txt"
    async with aiofiles.open(path, encoding="utf-8") as f:
        return await f.read()


async def load_qa_safe(fnum: int) -> tuple[int, dict[str, Any] | None]:
    """安全加载 QA 数据，缺失或损坏时返回 (fnum, None)."""
    try:
        return fnum, await load_qa(fnum)
    except FileNotFoundError:
        logger.warning("[warn] qa file %d not found", fnum)
        return fnum, None
    except json.JSONDecodeError, OSError, UnicodeDecodeError:
        logger.warning("[warn] qa file %d unreadable or corrupt", fnum)
        return fnum, None


async def load_history_cache(
    file_nums: list[int],
    *,
    needs_history: bool,
) -> dict[int, str]:
    """批量加载历史，按 needs_history 过滤."""
    if not needs_history:
        return {}

    async def _load_or_empty(fnum: int) -> tuple[int, str]:
        try:
            return fnum, await load_history(fnum)
        except OSError, UnicodeDecodeError:
            logger.warning(
                "[warn] history file %d not found or unreadable, using empty", fnum
            )
            return fnum, ""

    semaphore = asyncio.Semaphore(100)

    async def _limited_load_or_empty(fnum: int) -> tuple[int, str]:
        async with semaphore:
            return await _load_or_empty(fnum)

    history_pairs = await asyncio.gather(
        *(_limited_load_or_empty(f) for f in file_nums),
        return_exceptions=True,
    )
    result: dict[int, str] = {}
    for pair in history_pairs:
        if isinstance(pair, tuple):
            result[pair[0]] = pair[1]
        else:
            logger.warning("[warn] 加载历史文件失败: %s", pair)
    return result


async def load_prep(
    fnum: int,
    mtype: BenchMemoryMode,
) -> tuple[BenchMemoryMode, int, dict[str, Any] | None]:
    """加载单个 prep 数据."""
    if _is_prep_free(mtype):
        return mtype, fnum, {"type": mtype}
    pp = _prep_path(mtype, fnum)
    try:
        async with aiofiles.open(pp, encoding="utf-8") as f:
            parsed = json.loads(await f.read())
            if not isinstance(parsed, dict):
                logger.warning(
                    "[warn] prep file %s/%d root is not a dict, got %s",
                    mtype,
                    fnum,
                    type(parsed).__name__,
                )
                return mtype, fnum, None
            return mtype, fnum, parsed
    except FileNotFoundError:
        logger.debug("[skip] prep file %s/%d not found", mtype, fnum)
        return mtype, fnum, None
    except OSError, UnicodeDecodeError:
        logger.warning("[warn] prep file %s/%d unreadable: %s", mtype, fnum, pp)
        return mtype, fnum, None
    except json.JSONDecodeError:
        logger.warning(
            "[warn] corrupt prep file for %s file %d, skipping",
            mtype,
            fnum,
        )
        return mtype, fnum, None


async def load_prep_cache(
    file_nums: list[int],
    types: list[BenchMemoryMode],
) -> dict[tuple[BenchMemoryMode, int], dict[str, Any]]:
    """批量加载 prep 数据缓存."""
    # 限制并发数量，避免打开过多文件导致 EMFILE/OSError
    semaphore = asyncio.Semaphore(100)

    async def _limited_load_prep(
        f: int,
        t: BenchMemoryMode,
    ) -> tuple[BenchMemoryMode, int, dict[str, Any] | None]:
        async with semaphore:
            return await load_prep(f, t)

    prep_raw = await asyncio.gather(
        *(_limited_load_prep(f, t) for f in file_nums for t in types),
        return_exceptions=True,
    )
    data: dict[tuple[BenchMemoryMode, int], dict[str, Any]] = {}
    for item in prep_raw:
        if isinstance(item, tuple):
            mt, fn, d = item
            if d is not None:
                data[(mt, fn)] = d
        else:
            logger.warning("[warn] 加载 prep 数据失败: %s", item)
    return data
