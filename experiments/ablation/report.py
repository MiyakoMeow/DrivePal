"""实验报告生成."""

import html
import json
import logging
from pathlib import Path

from .types import GroupResult

logger = logging.getLogger(__name__)


def _write_group_json(results: dict[str, GroupResult], output_dir: Path) -> None:
    """写各组 JSON 和汇总 report.json。"""
    for group_name, gr in results.items():
        data = {
            "group": gr.group,
            "metrics": gr.metrics,
            "variant_results": [
                {
                    "scenario_id": r.scenario_id,
                    "variant": r.variant.value,
                    "decision": r.decision,
                    "modifications": r.modifications,
                    "latency_ms": r.latency_ms,
                }
                for r in gr.variant_results
            ],
            "judge_scores": [
                {
                    "scenario_id": s.scenario_id,
                    "variant": s.variant.value,
                    "safety_score": s.safety_score,
                    "reasonableness_score": s.reasonableness_score,
                    "overall_score": s.overall_score,
                    "violation_flags": s.violation_flags,
                }
                for s in gr.judge_scores
            ],
        }
        filepath = output_dir / f"{group_name}.json"
        filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    summary = {name: gr.metrics for name, gr in results.items()}
    summary_path = output_dir / "report.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))


def _generate_metrics_table(metrics: dict) -> str:
    """从一组 metrics 生成 HTML <table> 行。"""
    rows: list[str] = []
    for metric_name, metric_value in metrics.items():
        if isinstance(metric_value, dict):
            rows.append(
                f"<tr><td colspan='2'><b>{html.escape(metric_name)}</b></td></tr>"
            )
            for k, v in metric_value.items():
                if isinstance(v, (int, float, str)):
                    rows.append(
                        f"<tr><td>{html.escape(str(k))}</td><td>{html.escape(str(v))}</td></tr>"
                    )
        elif isinstance(metric_value, (int, float, str)):
            rows.append(
                f"<tr><td>{html.escape(metric_name)}</td><td>{html.escape(str(metric_value))}</td></tr>"
            )
    return "\n".join(rows)


def _generate_html_report(results: dict[str, GroupResult], output_dir: Path) -> None:
    """生成完整 HTML 报告。"""
    html_path = output_dir / "report.html"
    with html_path.open("w") as f:
        f.write(
            '<html><head><meta charset="utf-8"><title>消融实验报告</title></head><body>'
        )
        f.write("<h1>DrivePal-2 消融实验报告</h1>")
        for group_name, gr in results.items():
            f.write(f"<h2>{html.escape(group_name)} 组</h2>")
            f.write("<table border='1'>")
            f.write(_generate_metrics_table(gr.metrics))
            f.write("</table>")
        f.write("</body></html>")

    logger.info("报告已生成: %s", output_dir)


def render_report(results: dict[str, GroupResult], output_dir: Path) -> None:
    """编排：mkdir → 写 JSON → 生成 HTML。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_group_json(results, output_dir)
    _generate_html_report(results, output_dir)
