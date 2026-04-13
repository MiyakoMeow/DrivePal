"""基准测试结果收集与报告生成."""

import json
import logging
from collections import defaultdict
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
            logger.exception("构建指标失败: %s", mtype)
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


def report(output_path: Path | None = None) -> None:
    """从结果生成并打印基准测试报告."""
    output_dir = ensure_output_dir()
    all_results, failed_counts = collect_results(output_dir)
    report_data = build_report_metrics(all_results)

    for mtype, fc in failed_counts.items():
        metric = report_data.setdefault(mtype, {"total_failed": 0})
        metric["total_failed"] = fc

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
    logger.info("Report written to %s", out)

    for mtype, metric in report_data.items():
        esm = metric.get("exact_match_rate", 0)
        failed = metric.get("total_failed", 0)
        logger.info(
            "  %s: ESM=%s, F-F1=%s, V-F1=%s, Calls=%s%s",
            mtype.value,
            f"{esm:.2%}",
            f"{metric.get('state_f1_positive', 0):.4f}",
            f"{metric.get('state_f1_change', 0):.4f}",
            f"{metric.get('avg_pred_calls', 0):.1f}",
            f", Failed={failed}" if failed else "",
        )
