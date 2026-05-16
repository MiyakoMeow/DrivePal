"""实验报告生成."""

import logging
import math
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


def _build_variant_pairs(
    comp: dict, w: dict
) -> tuple[list[tuple[str, float, float]], str, float]:
    """构建变体配对列表与描述文本，容错 inf Cohen's d。"""
    pairs: list[tuple[str, float, float]] = []
    for vname, vdata in comp.items():
        if vname.startswith("_") or not isinstance(vdata, dict):
            continue
        d = vdata.get("cohens_d", 0)
        p = (w.get(vname) or {}).get("p_value", 1.0)
        pairs.append((vname, abs(d), p))
    desc_parts: list[str] = []
    for v, d, p in pairs:
        if math.isinf(d):
            desc_parts.append(f"{v.upper()} d=N/A (zero variance) p={p:.3f}")
        else:
            desc_parts.append(f"{v.upper()} d={d:.2f} p={p:.3f}")
    desc = "; ".join(desc_parts)
    worst_p = max(p for _, _, p in pairs) if pairs else 1.0
    return pairs, desc, worst_p


def _build_safety_statistical_note(metrics: dict) -> dict[str, Any]:
    """安全性组统计显著性标注——含 overall_score 和 safety_score 两维度。"""
    comparison = metrics.get("_comparison", {})
    wilcoxon = comparison.get("_wilcoxon", {})
    safety_comparison = metrics.get("_safety_comparison", {})
    safety_wilcoxon = safety_comparison.get("_wilcoxon", {})

    variant_rates: dict[str, float] = {}
    for k, v in metrics.items():
        if k.startswith("_") or not isinstance(v, dict):
            continue
        ocr = v.get("objective_compliance_rate")
        variant_rates[k] = ocr if ocr is not None else v.get("judge_compliance_rate", 0)
    rates_list = list(variant_rates.values())
    max_rate = max(rates_list) if rates_list else 0.0
    min_rate = min(rates_list) if rates_list else 0.0
    gap_pp = round((max_rate - min_rate) * 100)
    rates_desc = ", ".join(f"{k.upper()} {v:.0%}" for k, v in variant_rates.items())

    overall_pairs, overall_desc, overall_worst_p = _build_variant_pairs(
        comparison, wilcoxon
    )
    safety_pairs, safety_desc, safety_worst_p = _build_variant_pairs(
        safety_comparison, safety_wilcoxon
    )

    note = f"合规率 {rates_desc}（极差 {gap_pp}pp）；Overall: {overall_desc}；Safety: {safety_desc}。"
    overall_sig = "显著" if overall_worst_p < _ALPHA else "不显著"
    safety_sig = "显著" if safety_worst_p < _ALPHA else "不显著"
    note += f"Overall {overall_sig}，Safety {safety_sig}（α={_ALPHA}）。"
    if overall_worst_p >= _ALPHA and safety_worst_p >= _ALPHA:
        note += "建议 n=200+ 复验。"
    return {
        "note": note,
        "overall_score": {
            "variant_pairs": {
                v: {
                    "cohens_d": round(d, 2) if not math.isinf(d) else None,
                    "p_value": round(p, 3),
                    "p_value_raw": p,
                }
                for v, d, p in overall_pairs
            },
            "significant": overall_worst_p < _ALPHA,
            "note": overall_desc,
        },
        "safety_score": {
            "variant_pairs": {
                v: {
                    "cohens_d": round(d, 2) if not math.isinf(d) else None,
                    "p_value": round(p, 3),
                    "p_value_raw": p,
                }
                for v, d, p in safety_pairs
            },
            "significant": safety_worst_p < _ALPHA,
            "note": safety_desc,
        },
    }


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
        if name == "safety":
            entry["statistical_note"] = _build_safety_statistical_note(gr.metrics)
        summary[name] = entry
    out_path = run_dir / "summary.json"
    try:
        await write_json_atomic(out_path, summary)
        logger.info("全局总结已写入: %s", out_path)
    except OSError:
        logger.exception("Failed to write summary: %s", out_path)
