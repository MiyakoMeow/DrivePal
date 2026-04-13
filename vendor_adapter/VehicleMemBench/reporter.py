"""基准测试结果收集与报告生成."""

import json
import logging
from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from vendor_adapter.VehicleMemBench import BenchMemoryMode
from vendor_adapter.VehicleMemBench.model_config import get_benchmark_config
from vendor_adapter.VehicleMemBench.paths import (
    ensure_output_dir,
)

# 明确依赖 vendor 模块的私有函数以复用指标构建逻辑，
# 该函数无公开 API，vendor 模块为本项目内部使用不受 PEP8 约束。
from evaluation.model_evaluation import _build_metric  # isort: skip


if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


def collect_results(
    output_dir: Path,
) -> tuple[dict[BenchMemoryMode, list[dict[str, Any]]], dict[BenchMemoryMode, int]]:
    """从输出目录收集评估结果."""
    all_results: dict[BenchMemoryMode, list[dict[str, Any]]] = {}
    failed_counts: defaultdict[BenchMemoryMode, int] = defaultdict(int)
    for path in sorted(output_dir.glob("*/*/query_*.json")):
        try:
            mtype = BenchMemoryMode(path.parent.parent.name)
        except ValueError:
            continue
        data: dict[str, Any] | None = None
        try:
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError, OSError, UnicodeDecodeError:
            logger.warning("无法解析结果文件: %s", path)
            failed_counts[mtype] += 1
            continue
        if not isinstance(data, dict):
            logger.warning(
                "结果文件结构异常（非 dict），已跳过: %s (type=%s)",
                path,
                type(data).__name__,
            )
            failed_counts[mtype] += 1
            continue
        if data.get("failed"):
            failed_counts[mtype] += 1
            continue
        if mtype not in all_results:
            all_results[mtype] = []
        all_results[mtype].append(data)
    return all_results, failed_counts


def build_report_metrics(
    all_results: dict[BenchMemoryMode, list[dict[str, Any]]],
) -> dict[BenchMemoryMode, dict[str, Any]]:
    """构建评估报告指标."""
    cfg = get_benchmark_config()
    report_data: dict[BenchMemoryMode, dict[str, Any]] = {}
    for mtype, results in all_results.items():
        try:
            metric = _build_metric(results, model=cfg.model, memory_type=mtype)
        except Exception:
            logger.exception(
                "构建指标失败，已跳过该类型: mtype=%s, result_count=%d",
                mtype,
                len(results),
            )
            report_data[mtype] = {
                "build_error": True,
                "completed_tasks": 0,
                "total_failed": 0,
            }
            continue
        report_data[mtype] = metric
    return report_data


def compute_memory_scores(report_data: dict[BenchMemoryMode, dict[str, Any]]) -> None:
    """计算相对于 GOLD 的 memory_score."""
    gold_esm = report_data.get(BenchMemoryMode.GOLD, {}).get("exact_match_rate", 0)
    if not isinstance(gold_esm, int | float) or gold_esm <= 0:
        return
    for mtype, metric in report_data.items():
        if mtype != BenchMemoryMode.GOLD:
            auto_esm = metric.get("exact_match_rate", 0)
            if isinstance(auto_esm, int | float):
                metric["memory_score"] = auto_esm / gold_esm


def _md_overview(report_data: dict[BenchMemoryMode, dict[str, Any]]) -> str:
    """生成第1节：总览."""
    lines: list[str] = ["## 1. 总览\n"]
    if not report_data:
        lines.append("无数据。\n")
        return "\n".join(lines)

    has_gold = BenchMemoryMode.GOLD in report_data
    if not has_gold:
        lines.append("注意：未包含 GOLD 类型数据，Memory Score 和 Δ% 列不可用。\n")
    gold_esm = _num(report_data.get(BenchMemoryMode.GOLD, {}).get("exact_match_rate"))

    header = "| 记忆类型 | ESM | F1 Positive | F1 Change | Memory Score | Δ% (vs Gold) | Avg Calls | Avg Tokens | 失败数 |"
    sep = "|---|---|---|---|---|---|---|---|---|"
    lines.append(header)
    lines.append(sep)

    for mtype, metric in report_data.items():
        if metric.get("build_error"):
            lines.append(
                f"| {mtype.value} | 指标构建失败 | - | - | - | - | - | - | - |"
            )
            continue
        esm = _num(metric.get("exact_match_rate"))
        f1_pos = _num(metric.get("state_f1_positive"))
        f1_chg = _num(metric.get("state_f1_change"))
        ms = f"{_num(metric['memory_score']):.2%}" if "memory_score" in metric else "-"
        calls = _num(metric.get("avg_pred_calls"))
        tokens = _num(metric.get("avg_output_token"))
        failed = _num(metric.get("total_failed"))
        if has_gold and mtype != BenchMemoryMode.GOLD and gold_esm > 0:
            delta = (esm - gold_esm) / gold_esm
            delta_str = f"{delta:.2%}"
        else:
            delta_str = "-"
        lines.append(
            f"| {mtype.value} | {esm:.2%} | {f1_pos:.4f} | {f1_chg:.4f} | {ms} | {delta_str} | {calls:.1f} | {tokens:.1f} | {failed} |"
        )
    lines.append("")
    return "\n".join(lines)


_REASONING_TYPE_LABELS: dict[str, str] = {
    "preference_conflict": "偏好冲突",
    "conditional_constraint": "条件约束",
    "error_correction": "错误修正",
    "coreference_resolution": "共指消解",
    "state_shift": "状态迁移",
}


def _num(v: object, default: float = 0) -> int | float:
    """确保值为数字，None 或非数字类型返回默认值."""
    return v if isinstance(v, int | float) and not isinstance(v, bool) else default


def _md_memory_type_detail(
    mtype: BenchMemoryMode,
    metric: dict[str, Any],
    gold_metric: dict[str, Any] | None,
) -> str:
    """生成单个记忆类型的详细分析（由外层包裹 ## 2. 节标题）."""
    lines: list[str] = []
    lines.append(f"### {mtype.value}\n")

    if metric.get("build_error"):
        lines.append(
            "**指标构建失败**：该记忆类型的评估结果无法正常聚合，请检查原始数据。\n"
        )
        return "\n".join(lines)

    esm = _num(metric.get("exact_match_rate"))
    f1_pos = _num(metric.get("state_f1_positive"))
    f1_chg = _num(metric.get("state_f1_change"))
    f1_neg = _num(metric.get("state_f1_negative"))
    chg_acc = _num(metric.get("change_accuracy"))
    calls = _num(metric.get("avg_pred_calls"))
    tokens = _num(metric.get("avg_output_token"))
    failed = _num(metric.get("total_failed"))

    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| Exact Match Rate (ESM) | {esm:.2%} |")
    lines.append(f"| F1 Positive | {f1_pos:.4f} |")
    lines.append(f"| F1 Change | {f1_chg:.4f} |")
    lines.append(f"| F1 Negative | {f1_neg:.4f} |")
    lines.append(f"| Change Accuracy | {chg_acc:.4f} |")
    lines.append(f"| Avg Pred Calls | {calls:.1f} |")
    lines.append(f"| Avg Output Token | {tokens:.1f} |")
    lines.append(f"| 失败查询数 | {failed} |")
    if "memory_score" in metric:
        lines.append(f"| Memory Score | {_num(metric['memory_score']):.2%} |")
    lines.append("")

    lines.append(
        "该记忆类型的评估指标说明："
        "ESM（Exact Match Rate）衡量最终车辆状态与真值完全匹配的比例；"
        "F1 Positive 评估是否修改了正确的字段（字段级）；"
        "F1 Change 评估修改后的值是否正确（值级）；"
        "F1 Negative 评估是否避免了不应修改的字段被错误修改（负类）。"
        "Memory Score 表示相对于 GOLD 理论上限的 ESM 比值。详见 BENCHMARK-VehicleMemBench.md 第5节评估指标。\n"
    )

    by_rt = metric.get("by_reasoning_type", {})
    if by_rt:
        lines.append("**按推理类型细分：**\n")
        lines.append(
            "| 推理类型 | 样本数 | ESM | F1 Positive | F1 Change | Avg Calls |"
        )
        lines.append("|---|---|---|---|---|---|")
        for rt, raw_rt_metric in by_rt.items():
            rt_metric = raw_rt_metric or {}
            label = _format_reasoning_type(rt)
            rt_count = _num(rt_metric.get("count"))
            rt_esm = _num(rt_metric.get("exact_match_rate"))
            rt_f1p = _num(rt_metric.get("state_f1_positive"))
            rt_f1c = _num(rt_metric.get("state_f1_change"))
            rt_calls = _num(rt_metric.get("avg_pred_calls"))
            lines.append(
                f"| {label} | {rt_count} | {rt_esm:.2%} | {rt_f1p:.4f} | {rt_f1c:.4f} | {rt_calls:.1f} |"
            )
        lines.append("")

    if gold_metric is not None:
        gold_esm_val = _num(gold_metric.get("exact_match_rate"))
        if gold_esm_val > 0:
            delta = (esm - gold_esm_val) / gold_esm_val
            lines.append(
                f"**与 Gold 对比：** ESM 差距为 {delta:.2%}（Gold: {gold_esm_val:.2%}，本类型: {esm:.2%}）。\n"
            )

    return "\n".join(lines)


def _md_reasoning_cross_comparison(
    report_data: dict[BenchMemoryMode, dict[str, Any]],
) -> str:
    """生成第3节：按推理类型交叉对比."""
    lines: list[str] = ["## 3. 按推理类型交叉对比\n"]
    if not report_data:
        lines.append("无数据。\n")
        return "\n".join(lines)

    all_reasoning_types: set[str] = set()
    for metric in report_data.values():
        all_reasoning_types.update((metric.get("by_reasoning_type") or {}).keys())
    sorted_rt = sorted(all_reasoning_types)

    mtypes = sorted(report_data.keys())
    header = "| 推理类型 | " + " | ".join(mt.value for mt in mtypes) + " |"
    sep = "|---|" + "|".join("---" for _ in mtypes) + "|"
    lines.append(header)
    lines.append(sep)

    rt_best: dict[str, tuple[BenchMemoryMode, float]] = {}
    for rt in sorted_rt:
        label = _format_reasoning_type(rt)
        values: list[tuple[float, BenchMemoryMode]] = []
        for mt in mtypes:
            rt_data = (report_data[mt].get("by_reasoning_type") or {}).get(rt) or {}
            esm = _num(rt_data.get("exact_match_rate"))
            values.append((esm, mt))
        max_esm = max(v for v, _ in values) if values else 0
        best_mt = next(
            (mt for esm, mt in values if esm == max_esm and max_esm > 0), None
        )
        if best_mt is not None:
            rt_best[rt] = (best_mt, max_esm)
        cells: list[str] = []
        for esm, _mt in values:
            cell = f"{esm:.2%}"
            if esm == max_esm and max_esm > 0:
                cell = f"**{cell}**"
            cells.append(cell)
        lines.append(f"| {label} | " + " | ".join(cells) + " |")

    if rt_best:
        parts: list[str] = []
        for rt, (best_mt, best_esm) in sorted(rt_best.items()):
            label = _format_reasoning_type(rt)
            parts.append(f"{label}上，{best_mt.value}（{best_esm:.2%}）表现最佳")
        lines.append("；".join(parts) + "。")
    lines.append("")
    return "\n".join(lines)


def _format_calls(calls: list[dict[str, Any]]) -> str:
    """将工具调用列表格式化为函数名列表."""
    if not calls:
        return "（无）"
    return ", ".join(c.get("name", "?") for c in calls)


def _format_reasoning_type(rt: str | None) -> str:
    """格式化推理类型标签."""
    return _REASONING_TYPE_LABELS.get(rt or "", rt or "")


def _format_query_entry(q: dict[str, Any], extra_lines: list[str]) -> list[str]:
    """格式化单条查询的分析条目."""
    lines = [
        f"- Query: {q.get('query', '')}",
        f"  - 推理类型: {_format_reasoning_type(q.get('reasoning_type', ''))}",
        f"  - 预测调用: {_format_calls(q.get('pred_calls', []))}",
        f"  - 参考调用: {_format_calls(q.get('ref_calls', []))}",
    ]
    lines.extend(extra_lines)
    lines.append("")
    return lines


def _md_query_analysis(  # noqa: C901
    all_results: dict[BenchMemoryMode, list[dict[str, Any]]],
) -> str:
    """生成第4节：单条查询分析."""
    lines: list[str] = ["## 4. 单条查询分析\n"]
    if not all_results:
        lines.append("无查询数据。\n")
        return "\n".join(lines)

    def _query_sort_key(q: dict[str, Any]) -> tuple[str, int, int]:
        return (
            str(q.get("memory_type", "")),
            int(_num(q.get("source_file", 0))),
            int(_num(q.get("task_id", 0))),
        )

    for mtype, queries in all_results.items():
        if not queries:
            continue
        lines.append(f"### {mtype.value} 查询分析\n")

        successes = [q for q in queries if q.get("exact_match")]
        successes.sort(key=_query_sort_key)
        if successes:
            lines.append("**完全匹配案例（前3条）：**\n")
            for q in successes[:3]:
                lines.extend(_format_query_entry(q, ["  - 完全匹配: ✅"]))

        non_match = [q for q in queries if not q.get("exact_match")]
        fp_candidates = [
            q for q in non_match if _num((q.get("state_score") or {}).get("FP")) > 0
        ]
        fp_sorted = sorted(
            fp_candidates,
            key=lambda q: (
                -_num((q.get("state_score") or {}).get("FP")),
                *_query_sort_key(q),
            ),
        )
        if fp_sorted:
            lines.append("**过度修改案例（FP 最高，前3条）：**\n")
            for q in fp_sorted[:3]:
                state_score = q.get("state_score") or {}
                fp = _num(state_score.get("FP"))
                diffs = state_score.get("differences") or []
                extra: list[str] = [f"  - FP={fp}"]
                extra.extend(f"  - 差异: {d}" for d in diffs)
                lines.extend(_format_query_entry(q, extra))

        fn_candidates = [
            q for q in non_match if _num((q.get("tool_score") or {}).get("fn")) > 0
        ]
        fn_sorted = sorted(
            fn_candidates,
            key=lambda q: (
                -_num((q.get("tool_score") or {}).get("fn")),
                *_query_sort_key(q),
            ),
        )
        if fn_sorted:
            lines.append("**遗漏调用案例（tool_score.fn 最高，前3条）：**\n")
            for q in fn_sorted[:3]:
                tool_score = q.get("tool_score") or {}
                fn = _num(tool_score.get("fn"))
                state_score = q.get("state_score") or {}
                diffs = state_score.get("differences") or []
                extra = [f"  - FN={fn}"]
                extra.extend(f"  - 差异: {d}" for d in diffs)
                lines.extend(_format_query_entry(q, extra))

    return "\n".join(lines)


def _md_summary(report_data: dict[BenchMemoryMode, dict[str, Any]]) -> str:
    """生成第5节：总结."""
    lines: list[str] = ["## 5. 总结\n"]
    if not report_data:
        lines.append("无数据。\n")
        return "\n".join(lines)

    total_tasks = sum(
        int(_num(m.get("completed_tasks"))) + int(_num(m.get("total_failed")))
        for m in report_data.values()
    )
    n_types = len(report_data)

    sorted_types = sorted(
        report_data.items(),
        key=lambda x: (
            -1 if x[1].get("build_error") else _num(x[1].get("exact_match_rate"))
        ),
        reverse=True,
    )

    lines.append(
        f"本次评估共测试了 {n_types} 种记忆类型，"
        f"共完成 {total_tasks} 条查询评估。"
        f"按完全匹配率（ESM）排名：\n"
    )
    for rank, (mtype, metric) in enumerate(sorted_types, 1):
        if metric.get("build_error"):
            lines.append(f"{rank}. {mtype.value}（指标构建失败）")
        else:
            esm = _num(metric.get("exact_match_rate"))
            lines.append(f"{rank}. {mtype.value}（ESM={esm:.2%}）")
    lines.append("")

    gold_metric = report_data.get(BenchMemoryMode.GOLD)
    if gold_metric:
        gold_esm = _num(gold_metric.get("exact_match_rate"))
        non_gold = [(mt, m) for mt, m in sorted_types if mt != BenchMemoryMode.GOLD]
        if non_gold:
            best_mt, best_metric = non_gold[0]
            ms = (
                _num(best_metric.get("memory_score"))
                if "memory_score" in best_metric
                else 0
            )
            lines.append(
                f"GOLD 类型作为理论上限达到 {gold_esm:.2%}，"
                f"最优非 GOLD 类型 {best_mt.value} "
                f"达到其 {ms:.2%} 的水平。\n"
            )

    return "\n".join(lines)


def generate_markdown_report(
    output_dir: Path,
    report_data: dict[BenchMemoryMode, dict[str, Any]],
    all_results: dict[BenchMemoryMode, list[dict[str, Any]]],
) -> None:
    """生成 Markdown 格式基准测试报告."""
    now = datetime.now(tz=UTC)
    timestamp_display = now.strftime("%Y-%m-%d %H:%M:%S")
    first_metric = next(iter(report_data.values()), None)
    model_name = first_metric.get("model", "unknown") if first_metric else "unknown"
    type_names = ", ".join(mt.value for mt in report_data) if report_data else "无"

    parts: list[str] = [
        "# VehicleMemBench 基准测试报告\n",
        f"- 生成时间：{timestamp_display}",
        f"- 评估模型：{model_name}",
        f"- 记忆类型：{type_names}\n",
        _md_overview(report_data),
    ]

    gold_metric = report_data.get(BenchMemoryMode.GOLD)
    if report_data:
        detail_parts: list[str] = ["## 2. 记忆类型详细分析\n"]
        detail_parts.extend(
            _md_memory_type_detail(
                mtype,
                metric,
                gold_metric if mtype != BenchMemoryMode.GOLD else None,
            )
            for mtype, metric in report_data.items()
        )
        parts.extend(detail_parts)

    parts.append(_md_reasoning_cross_comparison(report_data))
    parts.append(_md_query_analysis(all_results))
    parts.append(_md_summary(report_data))

    content = "\n".join(parts)
    filename = f"report-{now.strftime('%Y%m%d-%H%M%S-%f')}.md"
    out_path = output_dir / filename
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        f.write(content)
    logger.info("Markdown 报告已写入: %s", out_path)


def report(output_path: Path | None = None) -> None:
    """从结果生成并打印基准测试报告."""
    output_dir = ensure_output_dir()
    all_results, failed_counts = collect_results(output_dir)
    report_data = build_report_metrics(all_results)

    for mtype, fc in failed_counts.items():
        metric = report_data.setdefault(mtype, {})
        if not metric.get("completed_tasks"):
            metric["build_error"] = True
        metric["total_failed"] = metric.get("total_failed", 0) + fc

    compute_memory_scores(report_data)

    serializable_data = {str(k): v for k, v in report_data.items()}
    out = output_path if output_path is not None else output_dir / "report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        with out.open("w", encoding="utf-8") as f:
            json.dump(serializable_data, f, ensure_ascii=False, indent=2)
    except OSError, TypeError:
        logger.exception("写入报告文件失败: %s", out)
        raise
    logger.info("报告已写入: %s", out)

    try:
        generate_markdown_report(out.parent, report_data, all_results)
    except Exception:
        logger.exception("生成 Markdown 报告失败")

    for mtype, metric in report_data.items():
        esm = _num(metric.get("exact_match_rate"))
        failed = _num(metric.get("total_failed"))
        logger.info(
            "  %s: ESM=%s, F-F1=%s, V-F1=%s, Calls=%s%s",
            mtype.value,
            f"{esm:.2%}",
            f"{_num(metric.get('state_f1_positive')):.4f}",
            f"{_num(metric.get('state_f1_change')):.4f}",
            f"{_num(metric.get('avg_pred_calls')):.1f}",
            f", Failed={failed}" if failed else "",
        )
