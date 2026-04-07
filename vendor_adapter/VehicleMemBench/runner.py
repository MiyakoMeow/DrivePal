"""VehicleMemBench 评估基准的测试运行器."""

import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from concurrent.futures import Future

import aiofiles

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

from evaluation.model_evaluation import (
    parse_answer_to_tools,
    get_list_module_tools_schema,
    split_history_by_day,
    build_memory_recursive_summary,
    build_memory_key_value,
    process_task_direct,
    process_task_with_memory,
    process_task_with_kv_memory,
    _build_metric,
    _run_vehicle_task_evaluation,
    MemoryStore as VMBMemoryStore,
)
from evaluation.agent_client import AgentClient


SUPPORTED_MEMORY_TYPES = {"gold", "summary", "kv", "memory_bank"}


@dataclass
class EvalContext:
    """单次 query 评估所需的共享上下文."""

    agent_client: AgentClient
    prep_data: dict
    file_num: int
    memory_type: str
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


def _parse_memory_types(memory_types: str) -> list[str]:
    types = [t.strip() for t in memory_types.split(",") if t.strip()]
    invalid = [t for t in types if t not in SUPPORTED_MEMORY_TYPES]
    if invalid:
        raise ValueError(
            f"Unsupported memory_types: {invalid}. "
            f"Supported: {sorted(SUPPORTED_MEMORY_TYPES)}"
        )
    return types


def parse_file_range(range_str: str) -> list[int]:
    """将形如 '1-5' 或 '1,3,5' 的文件范围字符串解析为整数列表."""
    result = []
    for part in range_str.split(","):
        part = part.strip()
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


async def prepare(
    file_range: str = "1-50",
    memory_types: str = "gold,summary,kv,memory_bank",
) -> None:
    """为指定文件范围和记忆类型准备基准测试数据."""
    file_nums = parse_file_range(file_range)
    types = _parse_memory_types(memory_types)
    agent_client = _get_agent_client()
    output_dir = _ensure_output_dir()
    semaphore = asyncio.Semaphore(_QUERY_CONCURRENCY_LIMIT)

    async def _load_or_empty(fnum: int) -> tuple[int, str]:
        try:
            return fnum, await _load_history(fnum)
        except FileNotFoundError:
            print(f"[warn] history file {fnum} not found, using empty")
            return fnum, ""

    history_pairs = await asyncio.gather(*(_load_or_empty(f) for f in file_nums))
    history_cache = dict(history_pairs)

    async def _task(fnum: int, mtype: str) -> None:
        result_path = output_dir / f"{mtype}_file_{fnum}.json"
        if result_path.exists():
            print(f"[skip] {mtype} file {fnum} already prepared")
            return

        print(f"[prepare] {mtype} file {fnum}...")
        try:
            history_text = "" if mtype == "gold" else history_cache.get(fnum, "")
            async with semaphore:
                result = await _prepare_single(agent_client, history_text, fnum, mtype)
            if result is not None:
                async with aiofiles.open(result_path, "w", encoding="utf-8") as f:
                    await f.write(json.dumps(result, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"[error] {mtype} file {fnum}: {e}")
            raise

    prep_results = await asyncio.gather(
        *(_task(fnum, mtype) for fnum in file_nums for mtype in types),
        return_exceptions=True,
    )
    failed = sum(1 for r in prep_results if isinstance(r, BaseException))
    if failed:
        print(f"[prepare] done with {failed} failures")


async def _prepare_single(
    agent_client: AgentClient,
    history_text: str,
    file_num: int,
    memory_type: str,
) -> dict | None:
    if memory_type == "gold":
        return {"type": "gold"}
    if memory_type == "summary":
        daily = split_history_by_day(history_text)
        mem_text, _, _ = await asyncio.to_thread(
            build_memory_recursive_summary, agent_client, daily
        )
        return {"type": "summary", "memory_text": mem_text}
    if memory_type == "kv":
        daily = split_history_by_day(history_text)
        store, _, _ = await asyncio.to_thread(
            build_memory_key_value, agent_client, daily
        )
        return {"type": "kv", "store": store.to_dict()}
    if memory_type in ADAPTERS:
        adapter_cls = ADAPTERS[memory_type]
        data_dir = _ensure_output_dir() / f"store_{memory_type}_{file_num}"
        adapter = adapter_cls(data_dir=data_dir)
        await adapter.add(history_text)
        return {"type": memory_type, "data_dir": str(data_dir)}
    print(f"[warn] unknown memory_type: {memory_type}")
    return None


async def run(
    file_range: str = "1-50",
    memory_types: str = "gold,summary,kv,memory_bank",
    reflect_num: int = 10,
) -> None:
    """为指定文件范围和记忆类型运行基准评估."""
    file_nums = parse_file_range(file_range)
    types = _parse_memory_types(memory_types)
    agent_client = _get_agent_client()
    output_dir = _ensure_output_dir()
    query_semaphore = asyncio.Semaphore(_QUERY_CONCURRENCY_LIMIT)

    async def _load_qa_safe(fnum: int) -> tuple[int, dict | None]:
        try:
            return fnum, await _load_qa(fnum)
        except FileNotFoundError:
            print(f"[warn] qa file {fnum} not found")
            return fnum, None

    qa_pairs = await asyncio.gather(*(_load_qa_safe(f) for f in file_nums))
    qa_cache = dict(qa_pairs)

    async def _load_prep(fnum: int, mtype: str) -> tuple[str, int, dict | None]:
        path = output_dir / f"{mtype}_file_{fnum}.json"
        try:
            async with aiofiles.open(path, encoding="utf-8") as f:
                return mtype, fnum, json.loads(await f.read())
        except FileNotFoundError:
            return mtype, fnum, None

    prep_raw = await asyncio.gather(
        *(_load_prep(f, t) for f in file_nums for t in types)
    )
    prep_cache: dict[tuple[str, int], dict | None] = {
        (mt, fn): data for mt, fn, data in prep_raw
    }

    async def _task(fnum: int, mtype: str) -> None:
        result_path = output_dir / f"{mtype}_file_{fnum}_results.json"
        if result_path.exists():
            print(f"[skip] {mtype} file {fnum} already has results")
            return

        prep_data = prep_cache.get((mtype, fnum))
        if prep_data is None:
            print(f"[skip] {mtype} file {fnum} not prepared")
            return

        qa_data = qa_cache.get(fnum)
        if qa_data is None:
            print(f"[skip] {mtype} file {fnum} qa data not found")
            return

        events = qa_data.get("related_to_vehicle_preference", [])
        print(f"[run] {mtype} file {fnum}: {len(events)} queries...")

        try:
            run_output = await _run_single(
                agent_client,
                events,
                prep_data,
                fnum,
                mtype,
                reflect_num,
                query_semaphore,
            )
            async with aiofiles.open(result_path, "w", encoding="utf-8") as f:
                await f.write(json.dumps(run_output, ensure_ascii=False, indent=2))
            failed = run_output.get("failed_count", 0)
            if failed:
                print(f"  [warn] {mtype} file {fnum}: {failed} queries failed")
        except Exception as e:
            print(f"[error] {mtype} file {fnum}: {e}")
            raise

    run_results = await asyncio.gather(
        *(_task(fnum, mtype) for fnum in file_nums for mtype in types),
        return_exceptions=True,
    )
    failed = sum(1 for r in run_results if isinstance(r, BaseException))
    if failed:
        print(f"[run] done with {failed} file-level failures")


async def _run_single(
    agent_client: AgentClient,
    events: list[dict],
    prep_data: dict,
    file_num: int,
    memory_type: str,
    reflect_num: int,
    query_semaphore: asyncio.Semaphore,
) -> dict:
    search_client = _build_search_client(prep_data, memory_type)

    kv_store = None
    if memory_type == "kv":
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

    async def _eval_event(idx: int, event: dict) -> dict | None:
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
        return result

    coros = [_eval_event(i, e) for i, e in enumerate(events)]
    raw = await asyncio.gather(*coros, return_exceptions=True)
    results = []
    failed_count = 0
    for r in raw:
        if isinstance(r, asyncio.CancelledError):
            raise r
        if isinstance(r, BaseException):
            print(f"  [error] query: {r}")
            failed_count += 1
            continue
        if r is not None:
            results.append(r)
    return {"results": results, "failed_count": failed_count}


def _build_search_client(prep_data: dict, memory_type: str) -> StoreClient | None:
    """为自定义适配器预构建搜索客户端（按 file+type 复用）."""
    if memory_type not in ADAPTERS:
        return None
    data_dir_str = prep_data.get("data_dir")
    if not data_dir_str:
        return None
    adapter_cls = ADAPTERS[memory_type]
    data_dir = Path(data_dir_str)
    adapter = adapter_cls(data_dir=data_dir)
    store = adapter.load()
    return adapter.get_search_client(store)


async def _evaluate_query(
    ctx: EvalContext,
    task: dict,
    idx: int,
    gold_memory: str,
) -> dict | None:
    """执行单个 query 的评估，同步 vendor 调用通过 asyncio.to_thread 包装."""
    if ctx.memory_type == "gold":
        return await asyncio.to_thread(
            process_task_direct,
            {**task, "history_text": gold_memory},
            idx,
            ctx.agent_client,
            ctx.reflect_num,
        )

    if ctx.memory_type == "summary":
        memory_text = ctx.prep_data.get("memory_text", "")
        return await asyncio.to_thread(
            process_task_with_memory,
            task,
            idx,
            memory_text,
            ctx.agent_client,
            ctx.reflect_num,
        )

    if ctx.memory_type == "kv":
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

    return None


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
                search_client.search(query=query, top_k=top_k), loop
            )
            results = future.result(timeout=_SEARCH_TIMEOUT)
            text, count = format_search_results(results)
            return {"success": True, "results": text, "count": count}
        except TimeoutError:
            if future is not None:
                future.cancel()
            print(f"  [warn] memory_search timeout: {query!r}")
            return {
                "success": False,
                "error": "search timed out",
                "results": "",
                "count": 0,
            }
        except RuntimeError as e:
            if "event loop" in str(e).lower():
                print(f"  [warn] memory_search: event loop error: {e}")
                return {"success": False, "error": str(e), "results": "", "count": 0}
            raise
        except Exception as e:
            print(f"  [warn] memory_search failed: {e}")
            return {"success": False, "error": str(e), "results": "", "count": 0}

    return _search


async def _run_custom_adapter_with_client(
    agent_client: AgentClient,
    task: dict,
    task_id: int,
    memory_type: str,
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


def report(output_path: Path | None = None) -> None:
    """从结果生成并打印基准测试报告."""
    output_dir = _ensure_output_dir()
    all_results: dict[str, list[dict]] = {}
    failed_counts: dict[str, int] = {}

    mtype_pattern = re.compile(r"^(.+?)_file_\d+_results$")
    for path in sorted(output_dir.glob("*_results.json")):
        m = mtype_pattern.match(path.stem)
        if not m:
            continue
        mtype = m.group(1)
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        results = data.get("results", []) if isinstance(data, dict) else data
        if not isinstance(results, list):
            continue
        if isinstance(data, dict) and "failed_count" in data:
            failed_counts[mtype] = failed_counts.get(mtype, 0) + data["failed_count"]
        if mtype not in all_results:
            all_results[mtype] = []
        all_results[mtype].extend(results)

    cfg = get_benchmark_config()
    report_data = {}
    for mtype, results in all_results.items():
        metric = _build_metric(results, model=cfg.model, memory_type=mtype)
        report_data[mtype] = metric

    for mtype, fc in failed_counts.items():
        if mtype in report_data:
            report_data[mtype]["total_failed"] = fc

    if "gold" in report_data:
        gold_esm = report_data["gold"].get("exact_match_rate", 0)
        for mtype in report_data:
            if mtype != "gold":
                auto_esm = report_data[mtype].get("exact_match_rate", 0)
                report_data[mtype]["memory_score"] = (
                    auto_esm / gold_esm if gold_esm > 0 else 0.0
                )

    out = output_path if output_path is not None else output_dir / "report.json"
    with out.open("w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)
    print(f"Report written to {out}")

    for mtype, metric in report_data.items():
        esm = metric.get("exact_match_rate", 0)
        failed = metric.get("total_failed", 0)
        print(
            f"  {mtype}: ESM={esm:.2%}, F-F1={metric.get('state_f1_positive', 0):.4f}, "
            f"V-F1={metric.get('state_f1_change', 0):.4f}, "
            f"Calls={metric.get('avg_pred_calls', 0):.1f}"
            + (f", Failed={failed}" if failed else "")
        )
