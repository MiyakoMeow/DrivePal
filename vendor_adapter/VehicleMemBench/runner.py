"""VehicleMemBench 评估基准的测试运行器."""

import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from concurrent.futures import Future

import aiofiles

from . import BenchMemoryMode

logger = logging.getLogger(__name__)


class VehicleMemBenchError(Exception):
    """VehicleMemBench 模块的基准错误."""


from .memory_adapters import ADAPTERS
from .memory_adapters.common import StoreClient, format_search_results
from .model_config import get_benchmark_config

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
VENDOR_DIR = PROJECT_ROOT / "vendor" / "VehicleMemBench"
BENCHMARK_DIR = VENDOR_DIR / "benchmark"
OUTPUT_DIR = PROJECT_ROOT / "data" / "benchmark"

try:
    _QUERY_CONCURRENCY_LIMIT = int(os.environ.get("BENCHMARK_QUERY_CONCURRENCY", "4"))
except ValueError:
    _QUERY_CONCURRENCY_LIMIT = 4
try:
    _SEARCH_TIMEOUT = int(os.environ.get("BENCHMARK_SEARCH_TIMEOUT", "60"))
except ValueError:
    _SEARCH_TIMEOUT = 60


def setup_vehiclemembench_path() -> None:
    """将 VehicleMemBench 路径添加到 sys.path."""
    for d in [VENDOR_DIR, VENDOR_DIR / "evaluation"]:
        d_str = str(d)
        if not any(Path(p).resolve() == Path(d_str).resolve() for p in sys.path):
            sys.path.insert(0, d_str)


setup_vehiclemembench_path()

from evaluation.agent_client import AgentClient
from evaluation.model_evaluation import (
    MemoryStore as VMBMemoryStore,
)
from evaluation.model_evaluation import (
    _build_metric,
    _run_vehicle_task_evaluation,
    build_memory_key_value,
    get_list_module_tools_schema,
    parse_answer_to_tools,
    process_task_direct,
    process_task_with_kv_memory,
    split_history_by_day,
)

SUPPORTED_MEMORY_TYPES: frozenset[BenchMemoryMode] = frozenset(BenchMemoryMode)
_PREP_FREE_TYPES: frozenset[BenchMemoryMode] = frozenset(
    {BenchMemoryMode.NONE, BenchMemoryMode.GOLD},
)


@dataclass
class EvalContext:
    """单次 query 评估所需的共享上下文."""

    agent_client: AgentClient
    prep_data: dict
    file_num: int
    memory_type: BenchMemoryMode
    reflect_num: int
    search_client: StoreClient | None
    kv_store: VMBMemoryStore | None = None


_CUSTOM_ADAPTER_SYSTEM_INSTRUCTION = (
    "You are an intelligent in-car AI assistant responsible for fulfilling user requests by calling the vehicle system API.\n"
    "You have access to a memory store containing user vehicle preferences.\n"
    "- Use memory_search(query, top_k) to look up relevant user preferences\n"
    "- Use list_module_tools(module_name='xxx') to discover available functions\n"
    "- Call the specific functions you need\n"
    "When the available information does not support setting a device to a specific value, "
    "perform only the minimal required action."
)

_CUSTOM_ADAPTER_INITIAL_TOOLS = [
    {"type": "function", "function": get_list_module_tools_schema()},
    {
        "type": "function",
        "function": {
            "name": "memory_search",
            "description": "Search user vehicle preferences by keyword",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
]


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
    cfg = get_benchmark_config()
    return AgentClient(
        api_base=cfg.base_url,
        api_key=cfg.api_key,
        model=cfg.model,
        temperature=cfg.temperature,
        max_tokens=cfg.max_tokens,
    )


async def _load_qa(file_num: int) -> dict:
    path = BENCHMARK_DIR / "qa_data" / f"qa_{file_num}.json"
    async with aiofiles.open(path, encoding="utf-8") as f:
        return json.loads(await f.read())


async def _load_history(file_num: int) -> str:
    path = BENCHMARK_DIR / "history" / f"history_{file_num}.txt"
    async with aiofiles.open(path, encoding="utf-8") as f:
        return await f.read()


def _ensure_output_dir() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


def file_output_dir(memory_type: BenchMemoryMode, file_num: int) -> Path:
    """返回指定记忆类型和文件编号的输出目录路径."""
    return OUTPUT_DIR / memory_type / f"file_{file_num}"


def prep_path(memory_type: BenchMemoryMode, file_num: int) -> Path:
    """返回指定记忆类型和文件编号的 prep 数据路径."""
    return file_output_dir(memory_type, file_num) / "prep.json"


def query_result_path(
    memory_type: BenchMemoryMode,
    file_num: int,
    event_index: int,
) -> Path:
    """返回指定记忆类型、文件编号和事件索引的查询结果路径."""
    return file_output_dir(memory_type, file_num) / f"query_{event_index}.json"


async def prepare(  # noqa: C901, PLR0915
    file_range: str = "1-50",
    memory_types: str = "none,gold,kv,memory_bank",
) -> None:
    """为指定文件范围和记忆类型准备基准测试数据."""
    file_nums = parse_file_range(file_range)
    types = _parse_memory_types(memory_types)
    _ensure_output_dir()
    semaphore = asyncio.Semaphore(_QUERY_CONCURRENCY_LIMIT)

    need_history = any(mtype not in _PREP_FREE_TYPES for mtype in types)
    agent_client: AgentClient | None = None
    if any(mtype not in _PREP_FREE_TYPES and mtype not in ADAPTERS for mtype in types):
        try:
            agent_client = _get_agent_client()
        except Exception as e:
            msg = "agent_client not initialized but required by memory types"
            raise VehicleMemBenchError(msg) from e

    history_cache: dict[int, str] = {}
    if need_history:

        async def _load_or_empty(fnum: int) -> tuple[int, str]:
            try:
                return fnum, await _load_history(fnum)
            except FileNotFoundError:
                logger.warning("[warn] history file %d not found, using empty", fnum)
                return fnum, ""

        history_pairs = await asyncio.gather(*(_load_or_empty(f) for f in file_nums))
        history_cache = dict(history_pairs)

    async def _task(fnum: int, mtype: BenchMemoryMode) -> None:
        fdir = file_output_dir(mtype, fnum)
        if mtype in _PREP_FREE_TYPES:
            if fdir.exists():
                logger.info("[skip] %s file %d already prepared", mtype, fnum)
                return
            fdir.mkdir(parents=True, exist_ok=True)
            logger.info("[prepare] %s file %d...", mtype, fnum)
            return

        pp = prep_path(mtype, fnum)
        if pp.exists():
            logger.info("[skip] %s file %d already prepared", mtype, fnum)
            return

        logger.info("[prepare] %s file %d...", mtype, fnum)
        try:
            history_text = history_cache.get(fnum, "")
            if mtype in ADAPTERS:
                store_dir = fdir / "store"
                async with semaphore:
                    store_dir.mkdir(parents=True, exist_ok=True)
                    adapter_cls = ADAPTERS[mtype]
                    adapter = adapter_cls(data_dir=store_dir)
                    await adapter.add(history_text)
                result = {"type": mtype, "data_dir": str(store_dir)}
            else:
                async with semaphore:
                    result = await _prepare_single(
                        agent_client,
                        history_text,
                        fnum,
                        mtype,
                    )
            if result is not None:
                fdir.mkdir(parents=True, exist_ok=True)
                async with aiofiles.open(pp, "w", encoding="utf-8") as f:
                    await f.write(json.dumps(result, ensure_ascii=False, indent=2))
        except Exception:
            logger.exception("[error] %s file %d", mtype, fnum)
            raise

    prep_results = await asyncio.gather(
        *(_task(fnum, mtype) for fnum in file_nums for mtype in types),
        return_exceptions=True,
    )
    failed = sum(1 for r in prep_results if isinstance(r, BaseException))
    if failed:
        logger.info("[prepare] done with %d failures", failed)


async def _prepare_single(
    agent_client: AgentClient,
    history_text: str,
    _file_num: int,
    memory_type: BenchMemoryMode,
) -> dict | None:
    if memory_type == BenchMemoryMode.KV:
        daily = split_history_by_day(history_text)
        store, _, _ = await asyncio.to_thread(
            build_memory_key_value,
            agent_client,
            daily,
        )
        return {"type": BenchMemoryMode.KV, "store": store.to_dict()}
    logger.warning("[warn] unknown memory_type: %s", memory_type)
    return None


async def run(  # noqa: C901
    file_range: str = "1-50",
    memory_types: str = "none,gold,kv,memory_bank",
    reflect_num: int = 10,
) -> None:
    """为指定文件范围和记忆类型运行基准评估."""
    file_nums = parse_file_range(file_range)
    types = _parse_memory_types(memory_types)
    agent_client = _get_agent_client()
    _ensure_output_dir()
    query_semaphore = asyncio.Semaphore(_QUERY_CONCURRENCY_LIMIT)

    async def _load_qa_safe(fnum: int) -> tuple[int, dict | None]:
        try:
            return fnum, await _load_qa(fnum)
        except FileNotFoundError:
            logger.warning("[warn] qa file %d not found", fnum)
            return fnum, None

    qa_pairs = await asyncio.gather(*(_load_qa_safe(f) for f in file_nums))
    qa_cache = dict(qa_pairs)

    async def _load_prep(
        fnum: int,
        mtype: BenchMemoryMode,
    ) -> tuple[BenchMemoryMode, int, dict | None]:
        if mtype in _PREP_FREE_TYPES:
            return mtype, fnum, {"type": mtype}
        pp = prep_path(mtype, fnum)
        try:
            async with aiofiles.open(pp, encoding="utf-8") as f:
                return mtype, fnum, json.loads(await f.read())
        except FileNotFoundError:
            return mtype, fnum, None
        except json.JSONDecodeError:
            logger.warning(
                "[warn] corrupt prep file for %s file %d, skipping",
                mtype,
                fnum,
            )
            return mtype, fnum, None

    prep_raw = await asyncio.gather(
        *(_load_prep(f, t) for f in file_nums for t in types),
    )
    prep_cache: dict[tuple[BenchMemoryMode, int], dict | None] = {
        (mt, fn): data for mt, fn, data in prep_raw
    }

    async def _task(fnum: int, mtype: BenchMemoryMode) -> None:
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
        await _run_single(
            agent_client,
            events,
            prep_data,
            fnum,
            mtype,
            reflect_num,
            query_semaphore,
        )

    run_results = await asyncio.gather(
        *(_task(fnum, mtype) for fnum in file_nums for mtype in types),
        return_exceptions=True,
    )
    failed = sum(1 for r in run_results if isinstance(r, BaseException))
    if failed:
        logger.info("[run] done with %d file-level failures", failed)


async def _run_single(  # noqa: PLR0913
    agent_client: AgentClient,
    events: list[dict],
    prep_data: dict,
    file_num: int,
    memory_type: BenchMemoryMode,
    reflect_num: int,
    query_semaphore: asyncio.Semaphore,
) -> None:
    search_client = await _build_search_client(prep_data, memory_type)

    kv_store = None
    if memory_type == BenchMemoryMode.KV:
        kv_store = VMBMemoryStore()
        kv_store.store = prep_data.get("store", {})

    ctx = EvalContext(
        agent_client=agent_client,
        prep_data=prep_data,
        file_num=file_num,
        memory_type=memory_type,
        reflect_num=reflect_num,
        search_client=search_client,
        kv_store=kv_store,
    )

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
            pass

        try:
            query = event.get("query", "")
            reasoning_type = event.get("reasoning_type", "")
            ref_calls = parse_answer_to_tools(event.get("new_answer", []))
            gold_memory = event.get("gold_memory", "")
            task: dict = {
                "query": query,
                "tools": ref_calls,
                "reasoning_type": reasoning_type,
            }
            async with query_semaphore:
                result = await _evaluate_query(ctx, task, idx, gold_memory)
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
        logger.warning("  [warn] %d queries failed silently", len(silent_failures))


async def _build_search_client(
    prep_data: dict,
    memory_type: BenchMemoryMode,
) -> StoreClient | None:
    """为自定义适配器预构建搜索客户端（按 file+type 复用）."""
    if memory_type not in ADAPTERS:
        return None
    data_dir_str = prep_data.get("data_dir")
    if not data_dir_str:
        return None
    adapter_cls = ADAPTERS[memory_type]
    data_dir = Path(data_dir_str)
    adapter = adapter_cls(data_dir=data_dir)
    store = await asyncio.to_thread(adapter.load)
    return adapter.get_search_client(store)


async def _evaluate_query(
    ctx: EvalContext,
    task: dict,
    idx: int,
    gold_memory: str,
) -> dict | None:
    """执行单个 query 的评估，同步 vendor 调用通过 asyncio.to_thread 包装."""
    if ctx.memory_type == BenchMemoryMode.NONE:
        return await asyncio.to_thread(
            process_task_direct,
            {**task, "history_text": ""},
            idx,
            ctx.agent_client,
            ctx.reflect_num,
        )

    if ctx.memory_type == BenchMemoryMode.GOLD:
        return await asyncio.to_thread(
            process_task_direct,
            {**task, "history_text": gold_memory},
            idx,
            ctx.agent_client,
            ctx.reflect_num,
        )

    if ctx.memory_type == BenchMemoryMode.KV:
        if ctx.kv_store is None:
            return None
        return await asyncio.to_thread(
            process_task_with_kv_memory,
            task,
            idx,
            ctx.kv_store,
            ctx.agent_client,
            ctx.reflect_num,
        )

    if ctx.search_client is not None:
        return await _run_custom_adapter_with_client(
            ctx.agent_client,
            task,
            idx,
            ctx.memory_type,
            ctx.reflect_num,
            ctx.search_client,
        )

    msg = f"query {idx}: no search client for {ctx.memory_type}"
    raise VehicleMemBenchError(msg)


def _make_sync_memory_search(
    search_client: StoreClient,
) -> Callable[[str, int], dict]:
    """为同步 vendor 代码创建同步的 memory_search 包装器.

    使用 run_coroutine_threadsafe 将异步搜索调度到主事件循环.
    在主事件循环线程中调用此工厂函数以捕获事件循环引用.
    """
    loop = asyncio.get_running_loop()

    def _search(query: str, top_k: int = 5) -> dict:
        future: Future | None = None
        try:
            future = asyncio.run_coroutine_threadsafe(
                search_client.search(query=query, top_k=top_k),
                loop,
            )
            results = future.result(timeout=_SEARCH_TIMEOUT)
        except TimeoutError:
            if future is not None:
                future.cancel()
            logger.warning("  [warn] memory_search timeout: %r", query)
            return {
                "success": False,
                "error": "search timed out",
                "results": "",
                "count": 0,
            }
        except RuntimeError as e:
            if "event loop" in str(e).lower():
                logger.warning("  [warn] memory_search: event loop error: %s", e)
                return {"success": False, "error": str(e), "results": "", "count": 0}
            raise
        except OSError as e:
            logger.warning("  [warn] memory_search failed: %s", e)
            return {"success": False, "error": str(e), "results": "", "count": 0}
        else:
            text, count = format_search_results(results)
            return {"success": True, "results": text, "count": count}

    return _search


async def _run_custom_adapter_with_client(  # noqa: PLR0913
    agent_client: AgentClient,
    task: dict,
    task_id: int,
    memory_type: BenchMemoryMode,
    reflect_num: int,
    search_client: StoreClient,
) -> dict | None:
    """使用预构建的搜索客户端运行自定义适配器评估.

    _run_vehicle_task_evaluation 是同步函数，通过 asyncio.to_thread 在线程池中执行。
    其调用的 memory_search 回调通过 run_coroutine_threadsafe 调度到主事件循环。
    """
    memory_funcs = {
        "memory_search": _make_sync_memory_search(search_client),
    }

    return await asyncio.to_thread(
        _run_vehicle_task_evaluation,
        task=task,
        task_id=task_id,
        agent_client=agent_client,
        reflect_num=reflect_num,
        system_instruction=_CUSTOM_ADAPTER_SYSTEM_INSTRUCTION,
        request_context=f"{memory_type} file task {task_id}",
        initial_tools=_CUSTOM_ADAPTER_INITIAL_TOOLS,
        memory_funcs=memory_funcs,
    )


def report(output_path: Path | None = None) -> None:  # noqa: C901, PLR0912
    """从结果生成并打印基准测试报告."""
    output_dir = _ensure_output_dir()
    all_results: dict[BenchMemoryMode, list[dict]] = {}
    failed_counts: dict[BenchMemoryMode, int] = {}

    for path in sorted(output_dir.glob("*/*/query_*.json")):
        try:
            mtype = BenchMemoryMode(path.parent.parent.name)
        except ValueError:
            continue
        data: dict | None = None
        try:
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError, OSError:
            logger.debug("无法解析结果文件: %s", path)
        if not isinstance(data, dict):
            continue
        if data.get("failed"):
            failed_counts[mtype] = failed_counts.get(mtype, 0) + 1
            continue
        if mtype not in all_results:
            all_results[mtype] = []
        all_results[mtype].append(data)

    cfg = get_benchmark_config()
    report_data: dict[BenchMemoryMode, dict] = {}
    for mtype, results in all_results.items():
        metric = _build_metric(results, model=cfg.model, memory_type=mtype)
        report_data[mtype] = metric

    for mtype, fc in failed_counts.items():
        if mtype in report_data:
            report_data[mtype]["total_failed"] = fc

    if BenchMemoryMode.GOLD in report_data:
        gold_esm = report_data[BenchMemoryMode.GOLD].get("exact_match_rate", 0)
        for mtype, metric in report_data.items():
            if mtype != BenchMemoryMode.GOLD:
                auto_esm = metric.get("exact_match_rate", 0)
                metric["memory_score"] = auto_esm / gold_esm if gold_esm > 0 else 0.0

    out = output_path if output_path is not None else output_dir / "report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)
    logger.info("Report written to %s", out)

    for mtype, metric in report_data.items():
        esm = metric.get("exact_match_rate", 0)
        failed = metric.get("total_failed", 0)
        logger.info(
            "  %s: ESM=%s, F-F1=%s, V-F1=%s, Calls=%s%s",
            mtype,
            f"{esm:.2%}",
            f"{metric.get('state_f1_positive', 0):.4f}",
            f"{metric.get('state_f1_change', 0):.4f}",
            f"{metric.get('avg_pred_calls', 0):.1f}",
            f", Failed={failed}" if failed else "",
        )
