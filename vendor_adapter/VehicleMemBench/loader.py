"""QA/历史/prep 数据加载."""

import asyncio
import json
import logging

import aiofiles

from vendor_adapter.VehicleMemBench import BenchMemoryMode
from vendor_adapter.VehicleMemBench.paths import (
    BENCHMARK_DIR,
)
from vendor_adapter.VehicleMemBench.paths import (
    prep_path as _prep_path,
)

logger = logging.getLogger(__name__)

_prep_free_types: frozenset[BenchMemoryMode] = frozenset(
    {BenchMemoryMode.NONE, BenchMemoryMode.GOLD},
)


async def load_qa(file_num: int) -> dict:
    """加载 QA JSON 数据."""
    path = BENCHMARK_DIR / "qa_data" / f"qa_{file_num}.json"
    async with aiofiles.open(path, encoding="utf-8") as f:
        return json.loads(await f.read())


async def load_history(file_num: int) -> str:
    """加载历史文本."""
    path = BENCHMARK_DIR / "history" / f"history_{file_num}.txt"
    async with aiofiles.open(path, encoding="utf-8") as f:
        return await f.read()


async def load_qa_safe(fnum: int) -> tuple[int, dict | None]:
    """安全加载 QA 数据，缺失或损坏时返回 (fnum, None)."""
    try:
        return fnum, await load_qa(fnum)
    except FileNotFoundError:
        logger.warning("[warn] qa file %d not found", fnum)
        return fnum, None
    except json.JSONDecodeError, OSError:
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
        except FileNotFoundError, OSError:
            logger.warning(
                "[warn] history file %d not found or unreadable, using empty", fnum
            )
            return fnum, ""

    history_pairs = await asyncio.gather(*(_load_or_empty(f) for f in file_nums))
    return dict(history_pairs)


async def load_prep(
    fnum: int,
    mtype: BenchMemoryMode,
) -> tuple[BenchMemoryMode, int, dict | None]:
    """加载单个 prep 数据."""
    if mtype in _prep_free_types:
        return mtype, fnum, {"type": mtype}
    pp = _prep_path(mtype, fnum)
    try:
        async with aiofiles.open(pp, encoding="utf-8") as f:
            return mtype, fnum, json.loads(await f.read())
    except FileNotFoundError, OSError:
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
) -> dict[tuple[BenchMemoryMode, int], dict | None]:
    """批量加载 prep 数据缓存."""
    prep_raw = await asyncio.gather(
        *(load_prep(f, t) for f in file_nums for t in types),
    )
    return {(mt, fn): data for mt, fn, data in prep_raw}
