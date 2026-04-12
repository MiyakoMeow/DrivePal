"""VehicleMemBench 评估基准的测试运行器（编排层）."""

import asyncio
import json
import logging
import os
from functools import lru_cache
from typing import TYPE_CHECKING, Any

import aiofiles

from . import BenchMemoryMode
from .loader import load_history_cache, load_prep_cache, load_qa_safe
from .model_config import get_benchmark_config
from .paths import (  # noqa: F401
    BENCHMARK_DIR,
    OUTPUT_DIR,
    PROJECT_ROOT,
    VENDOR_DIR,
    ensure_output_dir,
    file_output_dir,
    prep_path,
    query_result_path,
    setup_vehiclemembench_path,
)
from .reporter import report  # noqa: F401
from .strategies import STRATEGIES, VehicleMemBenchError

if TYPE_CHECKING:
    from collections.abc import Callable

    from evaluation.agent_client import AgentClient

    from vendor_adapter.VehicleMemBench.strategies import QueryEvaluator

logger = logging.getLogger(__name__)

try:
    _QUERY_CONCURRENCY_LIMIT = int(os.environ.get("BENCHMARK_QUERY_CONCURRENCY", "4"))
except ValueError:
    _QUERY_CONCURRENCY_LIMIT = 4

SUPPORTED_MEMORY_TYPES: frozenset[BenchMemoryMode] = frozenset(BenchMemoryMode)


def _parse_memory_types(memory_types: str) -> list[BenchMemoryMode]:
    types = [t.strip() for t in memory_types.split(",") if t.strip()]
    invalid = [t for t in types if t not in SUPPORTED_MEMORY_TYPES]
    if invalid:
        msg = f"Unsupported memory_types: {invalid}. Supported: {sorted(SUPPORTED_MEMORY_TYPES)}"
        raise ValueError(msg)
    return [BenchMemoryMode(t) for t in types]


def parse_file_range(range_str: str) -> list[int]:
    """将形如 '1-5' 或 '1,3,5' 的文件范围字符串解析为整数列表."""
    result = []
    for raw_part in range_str.split(","):
        part = raw_part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            a, b = int(a), int(b)
            result.extend(range(min(a, b), max(a, b) + 1))
        else:
            result.append(int(part))
    return sorted(set(result))


@lru_cache(maxsize=1)
def _get_agent_client() -> AgentClient:
    """获取或创建 agent client（带缓存）."""
    from evaluation.agent_client import AgentClient  # noqa: PLC0415

    cfg = get_benchmark_config()
    return AgentClient(
        api_base=cfg.base_url,
        api_key=cfg.api_key,
        model=cfg.model,
        temperature=cfg.temperature,
        max_tokens=cfg.max_tokens,
    )


def _resolve_agent_client(types: list[BenchMemoryMode]) -> AgentClient | None:
    """按需解析 agent client."""
    strategies_list = [STRATEGIES[t] for t in types]
    if any(s.needs_agent_for_prep() for s in strategies_list):
        try:
            return _get_agent_client()
        except Exception as e:
            msg = "agent_client not initialized but required by memory types"
            raise VehicleMemBenchError(msg) from e
    return None


async def prepare(
    file_range: str = "1-50",
    memory_types: str = "none,gold,kv,memory_bank",
) -> None:
    """为指定文件范围和记忆类型准备基准测试数据."""
    file_nums = parse_file_range(file_range)
    types = _parse_memory_types(memory_types)
    ensure_output_dir()
    semaphore = asyncio.Semaphore(_QUERY_CONCURRENCY_LIMIT)

    strategies_list = [STRATEGIES[t] for t in types]
    agent_client = _resolve_agent_client(types)
    needs_history = any(s.needs_history() for s in strategies_list)
    history_cache = await load_history_cache(file_nums, needs_history=needs_history)

    async def _prepare_one(fnum: int, mtype: BenchMemoryMode) -> None:
        strategy = STRATEGIES[mtype]
        fdir = file_output_dir(mtype, fnum)
        pp = prep_path(mtype, fnum)

        if not strategy.needs_history() and not strategy.needs_agent_for_prep():
            if fdir.exists():
                logger.info("[skip] %s file %d already prepared", mtype, fnum)
                return
            fdir.mkdir(parents=True, exist_ok=True)
            logger.info("[prepare] %s file %d...", mtype, fnum)
            return

        if pp.exists():
            logger.info("[skip] %s file %d already prepared", mtype, fnum)
            return

        logger.info("[prepare] %s file %d...", mtype, fnum)
        history_text = history_cache.get(fnum, "")
        try:
            result = await strategy.prepare(history_text, fdir, agent_client, semaphore)
        except Exception:
            logger.exception("[error] prepare %s file %d", mtype, fnum)
            raise
        if result is not None:
            fdir.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(pp, "w", encoding="utf-8") as f:
                await f.write(json.dumps(result, ensure_ascii=False, indent=2))

    prep_results = await asyncio.gather(
        *(_prepare_one(fnum, mtype) for fnum in file_nums for mtype in types),
        return_exceptions=True,
    )
    failed = sum(1 for r in prep_results if isinstance(r, BaseException))
    if failed:
        logger.info("[prepare] done with %d failures", failed)


async def run(
    file_range: str = "1-50",
    memory_types: str = "none,gold,kv,memory_bank",
    reflect_num: int = 10,
) -> None:
    """为指定文件范围和记忆类型运行基准评估."""
    from evaluation.model_evaluation import parse_answer_to_tools  # noqa: PLC0415

    file_nums = parse_file_range(file_range)
    types = _parse_memory_types(memory_types)
    agent_client = _get_agent_client()
    ensure_output_dir()

    qa_pairs = await asyncio.gather(*(load_qa_safe(f) for f in file_nums))
    qa_cache = dict(qa_pairs)
    prep_cache = await load_prep_cache(file_nums, types)
    query_semaphore = asyncio.Semaphore(_QUERY_CONCURRENCY_LIMIT)

    async def _run_one_type(fnum: int, mtype: BenchMemoryMode) -> None:
        prep_data = prep_cache.get((mtype, fnum))
        if prep_data is None:
            logger.info("[skip] %s file %d not prepared", mtype, fnum)
            return

        qa_data = qa_cache.get(fnum)
        if qa_data is None:
            logger.info("[skip] %s file %d qa data not found", mtype, fnum)
            return

        events = qa_data.get("related_to_vehicle_preference", [])
        if not events:
            return

        fdir = file_output_dir(mtype, fnum)
        fdir.mkdir(parents=True, exist_ok=True)
        logger.info("[run] %s file %d: %d queries...", mtype, fnum, len(events))

        strategy = STRATEGIES[mtype]
        evaluator = await strategy.create_evaluator(
            agent_client,
            prep_data,
            fnum,
            reflect_num,
            query_semaphore,
        )
        await _run_single(evaluator, mtype, fnum, events, parse_answer_to_tools)

    run_results = await asyncio.gather(
        *(_run_one_type(fnum, mtype) for fnum in file_nums for mtype in types),
        return_exceptions=True,
    )
    failed = sum(1 for r in run_results if isinstance(r, BaseException))
    if failed:
        logger.info("[run] done with %d file-level failures", failed)


async def _run_single(
    evaluator: QueryEvaluator,
    memory_type: BenchMemoryMode,
    file_num: int,
    events: list[dict],
    parse_answer_to_tools_fn: Callable[..., Any],
) -> None:
    """运行单个文件的查询评估."""

    async def _eval_and_save(idx: int, event: dict) -> None:
        qp = query_result_path(memory_type, file_num, idx)
        try:
            async with aiofiles.open(qp, encoding="utf-8") as f:
                existing = json.loads(await f.read())
            if isinstance(existing, dict) and not existing.get("failed"):
                return
        except FileNotFoundError:
            pass
        except json.JSONDecodeError:
            logger.warning("损坏的查询结果文件将被覆盖: %s", qp)

        try:
            query = event.get("query", "")
            reasoning_type = event.get("reasoning_type", "")
            ref_calls = parse_answer_to_tools_fn(event.get("new_answer", []))
            gold_memory = event.get("gold_memory", "")
            task: dict = {
                "query": query,
                "tools": ref_calls,
                "reasoning_type": reasoning_type,
            }
            result = await evaluator.evaluate(task, idx, gold_memory)
            if result is not None:
                result["source_file"] = file_num
                result["event_index"] = idx
                result["memory_type"] = memory_type
                async with aiofiles.open(qp, "w", encoding="utf-8") as f:
                    await f.write(json.dumps(result, ensure_ascii=False, indent=2))
        except Exception as e:
            logger.exception("  [error] query %d", idx)
            fail_record = {
                "failed": True,
                "error": str(e),
                "source_file": file_num,
                "event_index": idx,
                "memory_type": memory_type,
            }
            try:
                async with aiofiles.open(qp, "w", encoding="utf-8") as f:
                    await f.write(json.dumps(fail_record, ensure_ascii=False, indent=2))
            except OSError:
                logger.exception(
                    "  [error] failed to write error record for query %d",
                    idx,
                )

    gather_results = await asyncio.gather(
        *(_eval_and_save(i, e) for i, e in enumerate(events)),
        return_exceptions=True,
    )
    silent_failures = [r for r in gather_results if isinstance(r, BaseException)]
    if silent_failures:
        for sf in silent_failures:
            logger.warning("  [warn] query failed silently: %s", sf)
        logger.warning("  [warn] %d queries failed silently", len(silent_failures))
