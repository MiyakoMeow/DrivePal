"""实验报告生成."""

import logging
from pathlib import Path
from typing import Any

from ._io import write_json_atomic
from .types import GroupResult, JudgeScores

logger = logging.getLogger(__name__)


def _score_distribution(scores: list[JudgeScores]) -> dict:
    """各变体的分数分布统计.

    返回 {variant: {mean, distribution: {score: ratio}}}。
    """
    if not scores:
        return {}
    by_variant: dict[str, list[int]] = {}
    for s in scores:
        by_variant.setdefault(s.variant.value, []).append(s.overall_score)
    result = {}
    for variant, overalls in by_variant.items():
        n = len(overalls)
        result[variant] = {
            "mean": round(sum(overalls) / n, 2) if n else 0,
            "distribution": {
                str(score): round(overalls.count(score) / n, 2) for score in range(1, 6)
            },
        }
    return result


async def render_report(results: dict[str, GroupResult], run_dir: Path) -> None:
    """异步写全局 summary.json。"""
    summary: dict[str, Any] = {}
    for name, gr in results.items():
        summary[name] = {
            "group": gr.group,
            "metrics": gr.metrics,
            "result_count": len(gr.variant_results),
            "score_count": len(gr.judge_scores),
            "score_distributions": _score_distribution(gr.judge_scores),
        }
    out_path = run_dir / "summary.json"
    try:
        await write_json_atomic(out_path, summary)
        logger.info("全局总结已写入: %s", out_path)
    except OSError:
        logger.exception("Failed to write summary: %s", out_path)
