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
            # 按变体配对 (d, p)，避免不同变体的 d/p 交叉呈现为单一对比
            variant_pairs: list[tuple[str, float, float]] = []
            for vname, vdata in comparison.items():
                if vname.startswith("_") or not isinstance(vdata, dict):
                    continue
                d = vdata.get("cohens_d", 0)
                p = (wilcoxon.get(vname) or {}).get("p_value", 1.0)
                variant_pairs.append((vname, abs(d), p))
            stats_desc = "; ".join(
                f"{v.upper()} d={d:.2f} p={p:.3f}" for v, d, p in variant_pairs
            )
            worst_p = max(p for _, _, p in variant_pairs) if variant_pairs else 1.0
            # 动态计算各变体合规率——从 metrics 中遍历所有非 _ 前缀变体
            variant_rates: dict[str, float] = {
                k: v.get("objective_compliance_rate", v.get("compliance_rate", 0))
                for k, v in gr.metrics.items()
                if not k.startswith("_") and isinstance(v, dict)
            }
            rates_list = list(variant_rates.values())
            max_rate = max(rates_list) if rates_list else 0.0
            min_rate = min(rates_list) if rates_list else 0.0
            gap_pp = round((max_rate - min_rate) * 100)
            rates_desc = ", ".join(
                f"{k.upper()} {v:.0%}" for k, v in variant_rates.items()
            )
            note = f"合规率 {rates_desc}（极差 {gap_pp}pp）；{stats_desc}，"
            note += (
                f"未达统计显著（α={_ALPHA}）。建议 n=200+ 复验。"
                if worst_p >= _ALPHA
                else f"达统计显著（α={_ALPHA}）。"
            )
            entry["statistical_note"] = {
                "note": note,
                "variant_pairs": {
                    v: {
                        "cohens_d": round(d, 2),
                        "p_value": round(p, 3),
                        "p_value_raw": p,
                    }
                    for v, d, p in variant_pairs
                },
                "significant": worst_p < _ALPHA,
            }
        summary[name] = entry
    out_path = run_dir / "summary.json"
    try:
        await write_json_atomic(out_path, summary)
        logger.info("全局总结已写入: %s", out_path)
    except OSError:
        logger.exception("Failed to write summary: %s", out_path)
