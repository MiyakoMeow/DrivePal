"""ExecuteRunner：对每个后端执行测试用例、收集原始输出和评估指标."""

import json
import time
from pathlib import Path
from typing import Any

from app.agents.workflow import create_workflow
from app.experiment.runners.evaluate import (
    evaluate_context_relatedness,
    evaluate_semantic_accuracy,
)
from app.memory.types import MemoryMode
from app.storage.json_store import JSONStore

BACKEND_MODES = list(MemoryMode)


def _extract_output(result: str, store_dir: str) -> str:
    store = JSONStore(store_dir, "events.json", list)
    events = store.read()
    if events:
        last = events[-1]
        decision = last.get("decision", {})
        if isinstance(decision, str):
            return decision
        content = (
            decision.get("reminder_content")
            or decision.get("remind_content")
            or decision.get("content")
        )
        if content:
            return content
        reasoning = decision.get("reasoning", "")
        if reasoning:
            return reasoning
        raw = decision.get("raw", "")
        if raw:
            return raw
    return result or ""


def execute(prepared_dir: str) -> dict[str, Any]:
    """读取 prepared.json，对每个后端顺序执行测试用例，保存 raw results."""
    prepared_path = Path(prepared_dir) / "prepared.json"
    prepared: dict[str, Any] = json.loads(prepared_path.read_text(encoding="utf-8"))
    run_id = prepared["run_id"]
    test_cases = prepared["test_cases"]
    stores_root = Path(prepared_dir) / "stores"
    results_dir = Path(prepared_dir) / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    all_results: dict[str, Any] = {"run_id": run_id, "methods": {}}

    for mode in BACKEND_MODES:
        store_dir = str(stores_root / mode.value)
        if not Path(store_dir).is_dir():
            continue

        workflow = create_workflow(data_dir=store_dir, memory_mode=mode.value)
        cases: list[dict[str, Any]] = []

        for case in test_cases:
            case_id = case.get("id", "")
            start = time.time()
            try:
                result, event_id = workflow.run(case["input"])
                latency_ms = (time.time() - start) * 1000
                raw_output = _extract_output(result, store_dir)
                metrics = evaluate_semantic_accuracy(
                    case["input"],
                    case["type"],
                    raw_output,
                )
                relatedness = evaluate_context_relatedness(
                    case["input"],
                    case["type"],
                    raw_output,
                )
                print(f"[{mode.value}] {case_id} OK ({latency_ms:.0f}ms)")
                cases.append(
                    {
                        "id": case_id,
                        "input": case["input"],
                        "type": case["type"],
                        "output": result,
                        "raw_output": raw_output,
                        "event_id": event_id,
                        "latency_ms": latency_ms,
                        "task_completed": True,
                        "semantic_accuracy": metrics,
                        "context_relatedness": relatedness,
                        "error": None,
                    },
                )
            except Exception as e:
                latency_ms = (time.time() - start) * 1000
                print(f"[{mode.value}] {case_id} FAIL ({latency_ms:.0f}ms): {e}")
                cases.append(
                    {
                        "id": case_id,
                        "input": case["input"],
                        "type": case["type"],
                        "output": "",
                        "raw_output": "",
                        "event_id": None,
                        "latency_ms": latency_ms,
                        "task_completed": False,
                        "semantic_accuracy": 0.0,
                        "context_relatedness": 0.0,
                        "error": str(e),
                    },
                )

        method_result: dict[str, Any] = {
            "run_id": run_id,
            "method": mode.value,
            "cases": cases,
        }
        raw_path = results_dir / f"{mode.value}_raw.json"
        raw_path.write_text(
            json.dumps(method_result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        all_results["methods"][mode.value] = method_result

    return all_results
