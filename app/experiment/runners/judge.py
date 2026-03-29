"""JudgeRunner：用独立 judge 模型对每个后端的输出做多维评分."""

import json
import re
from pathlib import Path
from typing import Any

from app.memory.types import MemoryMode
from app.models.settings import get_judge_model

BACKEND_MODES = list(MemoryMode)

JUDGE_WEIGHTS: dict[str, float] = {
    "memory_recall": 0.25,
    "relevance": 0.25,
    "task_quality": 0.20,
    "coherence": 0.15,
    "helpfulness": 0.15,
}

JUDGE_PROMPT_TEMPLATE = """你是一个车载AI智能体的质量评估专家。请评估以下系统回复的质量。

## 用户输入
{input}

## 系统回复
{output}

## 任务类型
{task_type}

## 评估维度
请对以下每个维度打分（1-5分），并简要说明理由：

1. **记忆召回 (memory_recall)**: 系统是否正确利用了历史记忆/上下文信息？(1=完全未利用, 5=完美利用)
2. **响应相关性 (relevance)**: 回复是否与用户意图紧密相关？(1=完全无关, 5=高度相关)
3. **任务完成质量 (task_quality)**: 日程管理任务是否被正确处理？(1=完全错误, 5=完美完成)
4. **上下文一致性 (coherence)**: 回复在驾驶场景下是否合理连贯？(1=完全不连贯, 5=非常连贯)
5. **整体有用性 (helpfulness)**: 对驾驶员的实际帮助程度？(1=无帮助, 5=非常有帮助)

请严格按照以下JSON格式输出，不要输出其他内容：
{{"memory_recall": {{"score": 4, "reason": "理由"}}, "relevance": {{"score": 5, "reason": "理由"}}, "task_quality": {{"score": 3, "reason": "理由"}}, "coherence": {{"score": 4, "reason": "理由"}}, "helpfulness": {{"score": 4, "reason": "理由"}}}}"""


def _parse_judge_response(response: str) -> dict | None:
    text = response.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "memory_recall" in obj:
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    pattern = r'\{[^{}]*"memory_recall"[^{}]*\}'
    m = re.search(pattern, text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except (json.JSONDecodeError, ValueError):
            pass
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end > brace_start:
        try:
            obj = json.loads(text[brace_start : brace_end + 1])
            if isinstance(obj, dict) and "memory_recall" in obj:
                return obj
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _extract_score(dim_data: Any) -> float:
    if isinstance(dim_data, dict):
        return float(dim_data.get("score", 0))
    if isinstance(dim_data, (int, float)):
        return float(dim_data)
    return 0.0


def _compute_weighted_total(scores: dict) -> float:
    total = 0.0
    for dim, weight in JUDGE_WEIGHTS.items():
        total += _extract_score(scores.get(dim, {})) * weight
    return round(total, 2)


def _judge_case(judge_model, case: dict[str, Any]) -> dict[str, Any]:
    prompt = (
        JUDGE_PROMPT_TEMPLATE.replace("{input}", str(case.get("input", "")))
        .replace("{output}", str(case.get("output", "")))
        .replace("{task_type}", str(case.get("type", "general")))
    )
    try:
        response = judge_model.generate(prompt)
        parsed = _parse_judge_response(response)
        if parsed is None:
            return {"id": case["id"], "judge_error": "Failed to parse judge response"}
        missing = [d for d in JUDGE_WEIGHTS if d not in parsed]
        if len(missing) > 2:
            return {
                "id": case["id"],
                "judge_error": f"Incomplete scores, missing: {missing}",
            }
        for d in missing:
            parsed[d] = {"score": 3, "reason": "judge未评分，使用默认中值"}
        return {
            "id": case["id"],
            "scores": parsed,
            "weighted_total": _compute_weighted_total(parsed),
        }
    except Exception as e:
        return {"id": case["id"], "judge_error": str(e)}


def _judge_method(
    prepared_dir: Path,
    method: str,
    judge_model,
    judge_model_name: str,
) -> dict[str, Any]:
    raw_path = prepared_dir / "results" / f"{method}_raw.json"
    if not raw_path.exists():
        return {
            "run_id": "",
            "method": method,
            "judge_model": judge_model_name,
            "cases": [],
        }

    raw: dict[str, Any] = json.loads(raw_path.read_text(encoding="utf-8"))
    run_id = raw.get("run_id", "")
    raw_cases = raw.get("cases", [])

    judged_dir = prepared_dir / "judged"
    judged_dir.mkdir(parents=True, exist_ok=True)
    judged_path = judged_dir / f"{method}_judged.json"

    existing: dict[str, dict] = {}
    if judged_path.exists():
        prev = json.loads(judged_path.read_text(encoding="utf-8"))
        for c in prev.get("cases", []):
            if "judge_error" not in c:
                existing[c["id"]] = c

    judged_cases: list[dict[str, Any]] = []
    for case in raw_cases:
        case_id = case.get("id", "")
        if case_id in existing:
            judged_cases.append(existing[case_id])
            continue
        print(f"[judge:{method}] {case_id}")
        result = _judge_case(judge_model, case)
        judged_cases.append(result)

    result: dict[str, Any] = {
        "run_id": run_id,
        "method": method,
        "judge_model": judge_model_name,
        "cases": judged_cases,
    }
    judged_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def _build_final_report(
    run_id: str,
    judge_model_name: str,
    all_results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for method, result in all_results.items():
        cases = result.get("cases", [])
        if not cases:
            continue
        valid = [c for c in cases if "judge_error" not in c]
        n = len(valid)
        if n == 0:
            summary[method] = {
                "avg_weighted_total": 0.0,
                "avg_memory_recall": 0.0,
                "avg_relevance": 0.0,
                "avg_task_quality": 0.0,
                "avg_coherence": 0.0,
                "avg_helpfulness": 0.0,
                "avg_latency_ms": 0.0,
                "task_completion_rate": 0.0,
                "case_count": 0,
            }
            continue

        wt = sum(c.get("weighted_total", 0) for c in valid) / n
        dim_avgs: dict[str, float] = {}
        for dim in JUDGE_WEIGHTS:
            s = 0.0
            for c in valid:
                s += _extract_score(c.get("scores", {}).get(dim, {}))
            dim_avgs[dim] = round(s / n, 2)

        latency_total = 0.0
        completed = 0
        total_cases = len(cases)
        raw_cases = []
        rp = (
            Path(all_results[method].get("_prepared_dir", ""))
            / "results"
            / f"{method}_raw.json"
        )
        try:
            raw_data = json.loads(rp.read_text(encoding="utf-8"))
            raw_cases = raw_data.get("cases", [])
        except Exception:
            pass

        for rc in raw_cases:
            latency_total += rc.get("latency_ms", 0)
            if rc.get("task_completed"):
                completed += 1

        summary[method] = {
            "avg_weighted_total": round(wt, 2),
            **{f"avg_{k}": v for k, v in dim_avgs.items()},
            "avg_latency_ms": round(latency_total / max(total_cases, 1), 1),
            "task_completion_rate": round(completed / max(total_cases, 1), 2),
            "case_count": total_cases,
        }

    return {
        "run_id": run_id,
        "judge_model": judge_model_name,
        "summary": summary,
    }


def judge(prepared_dir: str) -> dict[str, Any]:
    """对所有后端进行 judge 评分，生成 final_report.json."""
    prepared_path = Path(prepared_dir)
    judge_model = get_judge_model()
    judge_model_name = (
        judge_model.providers[0].provider.model if judge_model.providers else "unknown"
    )

    run_id = ""
    raw_path = prepared_path / "results" / f"{BACKEND_MODES[0].value}_raw.json"
    if raw_path.exists():
        data = json.loads(raw_path.read_text(encoding="utf-8"))
        run_id = data.get("run_id", "")

    all_results: dict[str, dict[str, Any]] = {}
    for mode in BACKEND_MODES:
        result = _judge_method(prepared_path, mode.value, judge_model, judge_model_name)
        result["_prepared_dir"] = str(prepared_path)
        all_results[mode.value] = result

    report = _build_final_report(run_id, judge_model_name, all_results)

    judged_dir = prepared_path / "judged"
    judged_dir.mkdir(parents=True, exist_ok=True)
    report_path = judged_dir / "final_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report
