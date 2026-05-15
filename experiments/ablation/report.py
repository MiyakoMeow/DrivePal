"""实验报告生成."""

import logging
from pathlib import Path
from typing import Any

from ._io import write_json_atomic
from .types import GroupResult, JudgeScores

logger = logging.getLogger(__name__)

_ALPHA = 0.05


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
        entry: dict[str, Any] = {
            "group": gr.group,
            "metrics": gr.metrics,
            "result_count": len(gr.variant_results),
            "score_count": len(gr.judge_scores),
            "score_distributions": _score_distribution(gr.judge_scores),
        }
        # 安全性组加统计显著性标注
        if name == "safety":
            comparison = gr.metrics.get("_comparison", {})
            wilcoxon = comparison.get("_wilcoxon", {})
            p_values = [
                v.get("p_value", 1.0) for v in wilcoxon.values() if isinstance(v, dict)
            ]
            d_values = [
                abs(v.get("cohens_d", 0))
                for k, v in comparison.items()
                if isinstance(v, dict) and not k.startswith("_")
            ]
            worst_p = max(p_values) if p_values else 1.0
            worst_d = max(d_values) if d_values else 0.0
            # 动态计算各变体合规率
            full_rate = gr.metrics.get("full", {}).get("compliance_rate", 0)
            no_rules_rate = gr.metrics.get("no-rules", {}).get("compliance_rate", 0)
            no_prob_rate = gr.metrics.get("no-prob", {}).get("compliance_rate", 0)
            max_rate = max(full_rate, no_rules_rate, no_prob_rate)
            min_rate = min(full_rate, no_rules_rate, no_prob_rate)
            gap_pp = round((max_rate - min_rate) * 100)
            entry["statistical_note"] = {
                "note": (
                    f"合规率 Full {full_rate:.0%}, NO_RULES {no_rules_rate:.0%}, "
                    f"NO_PROB {no_prob_rate:.0%}（极差 {gap_pp}pp），"
                    f"但 Cohen's d={worst_d:.2f}, Wilcoxon p={worst_p:.2f}，"
                    f"未达统计显著（α={_ALPHA}）。建议 n=200+ 复验。"
                ),
                "cohens_d": round(worst_d, 2),
                "p_value": round(worst_p, 2),
                "significant": worst_p < _ALPHA,
            }
        summary[name] = entry
    out_path = run_dir / "summary.json"
    try:
        await write_json_atomic(out_path, summary)
        logger.info("全局总结已写入: %s", out_path)
    except OSError:
        logger.exception("Failed to write summary: %s", out_path)
