"""基准测试结果收集与报告生成."""

import json
import logging
from typing import TYPE_CHECKING

from vendor_adapter.VehicleMemBench import BenchMemoryMode
from vendor_adapter.VehicleMemBench.model_config import get_benchmark_config
from vendor_adapter.VehicleMemBench.paths import (
    ensure_output_dir,
)

from evaluation.model_evaluation import _build_metric  # isort: skip

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


def collect_results(
    output_dir: Path,
) -> tuple[dict[BenchMemoryMode, list[dict]], dict[BenchMemoryMode, int]]:
    """从输出目录收集评估结果."""
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
            logger.warning("无法解析结果文件: %s", path)
            failed_counts[mtype] = failed_counts.get(mtype, 0) + 1
        if not isinstance(data, dict):
            continue
        if data.get("failed"):
            failed_counts[mtype] = failed_counts.get(mtype, 0) + 1
            continue
        if mtype not in all_results:
            all_results[mtype] = []
        all_results[mtype].append(data)
    return all_results, failed_counts


def build_report_metrics(
    all_results: dict[BenchMemoryMode, list[dict]],
) -> dict[BenchMemoryMode, dict]:
    """构建评估报告指标."""
    cfg = get_benchmark_config()
    report_data: dict[BenchMemoryMode, dict] = {}
    for mtype, results in all_results.items():
        metric = _build_metric(results, model=cfg.model, memory_type=mtype)
        report_data[mtype] = metric
    return report_data


def compute_memory_scores(report_data: dict[BenchMemoryMode, dict]) -> None:
    """计算相对于 GOLD 的 memory_score."""
    gold_esm = report_data.get(BenchMemoryMode.GOLD, {}).get("exact_match_rate", 0)
    if gold_esm <= 0:
        return
    for mtype, metric in report_data.items():
        if mtype != BenchMemoryMode.GOLD:
            auto_esm = metric.get("exact_match_rate", 0)
            metric["memory_score"] = auto_esm / gold_esm


def report(output_path: Path | None = None) -> None:
    """从结果生成并打印基准测试报告."""
    output_dir = ensure_output_dir()
    all_results, failed_counts = collect_results(output_dir)
    report_data = build_report_metrics(all_results)

    for mtype, fc in failed_counts.items():
        metric = report_data.setdefault(mtype, {"total_failed": 0})
        metric["total_failed"] = fc

    compute_memory_scores(report_data)

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
