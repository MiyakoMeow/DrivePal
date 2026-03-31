"""VehicleMemBench 评估基准的测试运行器."""

import sys
import os
import json
from pathlib import Path
from typing import TYPE_CHECKING, Optional, cast

from adapters.memory_adapters import ADAPTERS
from adapters.memory_adapters.common import (
    BaselineMemory,
    MemoryType,
    format_search_results,
)
from adapters.model_config import (
    get_benchmark_client,
    get_benchmark_model_name,
    get_benchmark_temperature,
    get_benchmark_max_tokens,
)

if TYPE_CHECKING:
    from adapters.memory_adapters.memory_bank_adapter import MemoryBankAdapter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = PROJECT_ROOT / "vendor" / "VehicleMemBench"
BENCHMARK_DIR = VENDOR_DIR / "benchmark"
OUTPUT_DIR = PROJECT_ROOT / "data" / "benchmark"


def setup_vehiclemembench_path() -> None:
    """将 VehicleMemBench 路径添加到 sys.path."""
    for d in [VENDOR_DIR, VENDOR_DIR / "evaluation"]:
        d_str = str(d)
        if not any(os.path.abspath(p) == os.path.abspath(d_str) for p in sys.path):
            sys.path.insert(0, d_str)


setup_vehiclemembench_path()

from evaluation.model_evaluation import (
    parse_answer_to_tools,
    get_list_module_tools_schema,
    process_task_direct,
    process_task_with_memory,
    process_task_with_kv_memory,
    _build_metric,
    _run_vehicle_task_evaluation,
    MemoryStore as VMBMemoryStore,
)
from evaluation.agent_client import AgentClient


SUPPORTED_MEMORY_TYPES: set[MemoryType] = set(MemoryType)


def _parse_memory_types(memory_types: str) -> list[MemoryType]:
    type_strs = [t.strip() for t in memory_types.split(",") if t.strip()]
    invalid = [t for t in type_strs if MemoryType(t) not in SUPPORTED_MEMORY_TYPES]
    if invalid:
        raise ValueError(
            f"Unsupported memory_types: {invalid}. "
            f"Supported: {sorted(m.value for m in SUPPORTED_MEMORY_TYPES)}"
        )
    return [MemoryType(t) for t in type_strs]


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


def _get_agent_client() -> AgentClient:
    client = get_benchmark_client()
    return AgentClient(
        api_base=str(client.base_url),
        api_key=client.api_key,
        model=get_benchmark_model_name(),
        temperature=get_benchmark_temperature(),
        max_tokens=get_benchmark_max_tokens(),
    )


def _load_qa(file_num: int) -> dict:
    path = BENCHMARK_DIR / "qa_data" / f"qa_{file_num}.json"
    with open(path) as f:
        return json.load(f)


def _load_history(file_num: int) -> str:
    path = BENCHMARK_DIR / "history" / f"history_{file_num}.txt"
    with open(path) as f:
        return f.read()


def _get_output_dir() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


def prepare(
    file_range: str = "1-50",
    memory_types: str = "gold,summary,kv,memory_bank",
) -> None:
    """为指定文件范围和记忆类型准备基准测试数据."""
    file_nums = parse_file_range(file_range)
    types = _parse_memory_types(memory_types)
    agent_client = _get_agent_client()
    output_dir = _get_output_dir()

    for fnum in file_nums:
        history_text = _load_history(fnum)
        for mtype in types:
            result_path = output_dir / f"{mtype.value}_file_{fnum}.json"
            if result_path.exists():
                print(f"[skip] {mtype.value} file {fnum} already prepared")
                continue

            print(f"[prepare] {mtype.value} file {fnum}...")
            try:
                result = _prepare_single(agent_client, history_text, fnum, mtype)
                if result is not None:
                    with open(result_path, "w") as f:
                        json.dump(result, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"[error] {mtype} file {fnum}: {e}")
                continue


def _prepare_single(
    agent_client: AgentClient, history_text: str, file_num: int, memory_type: MemoryType
) -> dict | None:
    if memory_type not in ADAPTERS:
        return None
    adapter_cls = ADAPTERS[memory_type]
    adapter = adapter_cls(
        data_dir=_get_output_dir() / f"store_{memory_type.value}_{file_num}"
    )
    store = adapter.add(history_text, agent_client=agent_client)
    if isinstance(store, BaselineMemory):
        return {
            "type": store.memory_type.value,
            "memory_text": store.memory_text,
            "kv_store": store.kv_store,
        }
    return {"type": memory_type.value, "data_dir": str(adapter.data_dir)}


def run(
    file_range: str = "1-50",
    memory_types: str = "gold,summary,kv,memory_bank",
    reflect_num: int = 10,
) -> None:
    """为指定文件范围和记忆类型运行基准评估."""
    file_nums = parse_file_range(file_range)
    types = _parse_memory_types(memory_types)
    agent_client = _get_agent_client()
    output_dir = _get_output_dir()

    for fnum in file_nums:
        qa_data = _load_qa(fnum)
        history_text = _load_history(fnum)
        events = qa_data.get("related_to_vehicle_preference", [])
        for mtype in types:
            result_path = output_dir / f"{mtype.value}_file_{fnum}_results.json"
            prep_path = output_dir / f"{mtype.value}_file_{fnum}.json"
            if not prep_path.exists():
                print(f"[skip] {mtype.value} file {fnum} not prepared")
                continue

            with open(prep_path) as f:
                prep_data = json.load(f)

            print(f"[run] {mtype.value} file {fnum}: {len(events)} queries...")
            try:
                results = _run_single(
                    agent_client,
                    events,
                    history_text,
                    prep_data,
                    fnum,
                    mtype,
                    reflect_num,
                )
                with open(result_path, "w") as f:
                    json.dump(results, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"[error] {mtype.value} file {fnum}: {e}")
                continue


def _run_single(
    agent_client: AgentClient,
    events: list[dict],
    history_text: str,
    prep_data: dict,
    file_num: int,
    memory_type: MemoryType,
    reflect_num: int,
) -> list[dict]:
    results = []
    for i, event in enumerate(events):
        query = event.get("query", "")
        reasoning_type = event.get("reasoning_type", "")
        ref_calls = parse_answer_to_tools(event.get("new_answer", []))
        gold_memory = event.get("gold_memory", "")
        task: dict = {
            "query": query,
            "tools": ref_calls,
            "reasoning_type": reasoning_type,
        }

        try:
            if memory_type == MemoryType.NONE:
                result = process_task_direct(task, i, agent_client, reflect_num)
            elif memory_type == MemoryType.GOLD:
                task["history_text"] = gold_memory
                result = process_task_direct(task, i, agent_client, reflect_num)
            elif memory_type == MemoryType.SUMMARY:
                memory_text = prep_data.get("memory_text", "")
                result = process_task_with_memory(
                    task, i, memory_text, agent_client, reflect_num
                )
            elif memory_type == MemoryType.KV:
                vmb_store = VMBMemoryStore()
                vmb_store.store = prep_data.get("kv_store", {})
                result = process_task_with_kv_memory(
                    task, i, vmb_store, agent_client, reflect_num
                )
            elif memory_type in ADAPTERS:
                result = _run_custom_adapter(
                    agent_client, task, i, prep_data, memory_type, reflect_num
                )
            else:
                continue

            if result:
                result["source_file"] = file_num
                result["event_index"] = i
                result["memory_type"] = memory_type.value
                results.append(result)
        except Exception as e:
            print(f"  [error] query {i}: {e}")
            continue

    return results


def _run_custom_adapter(
    agent_client: AgentClient,
    task: dict,
    task_id: int,
    prep_data: dict,
    memory_type: MemoryType,
    reflect_num: int,
) -> dict | None:
    if memory_type != MemoryType.MEMORY_BANK:
        raise ValueError(
            f"_run_custom_adapter only supports memory_bank, got {memory_type}"
        )
    adapter_cls = ADAPTERS[memory_type]
    data_dir = Path(prep_data["data_dir"])
    adapter = cast("MemoryBankAdapter", adapter_cls(data_dir=data_dir))

    store = adapter.add("")
    client = adapter.get_search_client(store)

    system_instruction = (
        "You are an intelligent in-car AI assistant responsible for fulfilling user requests by calling the vehicle system API.\n"
        "You have access to a memory store containing user vehicle preferences.\n"
        "- Use memory_search(query, top_k) to look up relevant user preferences\n"
        "- Use list_module_tools(module_name='xxx') to discover available functions\n"
        "- Call the specific functions you need\n"
        "When the available information does not support setting a device to a specific value, "
        "perform only the minimal required action."
    )

    initial_tools = [
        {"type": "function", "function": get_list_module_tools_schema()},
        {
            "type": "function",
            "function": {
                "name": "memory_search",
                "description": "Search user vehicle preferences by keyword",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
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

    def _memory_search(query: str, top_k: int = 5) -> dict:
        results = client.search(query=query, top_k=top_k)
        text, count = format_search_results(results)
        return {"success": True, "results": text, "count": count}

    memory_funcs = {
        "memory_search": _memory_search,
    }

    return _run_vehicle_task_evaluation(
        task=task,
        task_id=task_id,
        agent_client=agent_client,
        reflect_num=reflect_num,
        system_instruction=system_instruction,
        request_context=f"{memory_type.value} file task {task_id}",
        initial_tools=initial_tools,
        memory_funcs=memory_funcs,
    )


def report(output_path: Optional[Path] = None) -> None:
    """从结果生成并打印基准测试报告."""
    output_dir = _get_output_dir()
    all_results = {}

    for path in sorted(output_dir.glob("*_results.json")):
        mtype = path.stem.replace("_results", "").rsplit("_file_", 1)[0]
        with open(path) as f:
            results = json.load(f)
        if mtype not in all_results:
            all_results[mtype] = []
        all_results[mtype].extend(results)

    report_data = {}
    for mtype, results in all_results.items():
        metric = _build_metric(
            results, model=get_benchmark_model_name(), memory_type=mtype
        )
        report_data[mtype] = metric

    gold_key = MemoryType.GOLD.value
    if gold_key in report_data:
        gold_esm = report_data[gold_key].get("exact_match_rate", 0)
        for mtype in report_data:
            if mtype != gold_key:
                auto_esm = report_data[mtype].get("exact_match_rate", 0)
                report_data[mtype]["memory_score"] = (
                    auto_esm / gold_esm if gold_esm > 0 else 0.0
                )

    out = output_path if output_path is not None else output_dir / "report.json"
    with open(out, "w") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)
    print(f"Report written to {out}")

    for mtype, metric in report_data.items():
        esm = metric.get("exact_match_rate", 0)
        print(
            f"  {mtype}: ESM={esm:.2%}, F-F1={metric.get('state_f1_positive', 0):.4f}, "
            f"V-F1={metric.get('state_f1_change', 0):.4f}, "
            f"Calls={metric.get('avg_pred_calls', 0):.1f}"
        )
