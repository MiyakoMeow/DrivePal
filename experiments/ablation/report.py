"""实验报告生成."""

import html
import json
import logging
from pathlib import Path

from .types import GroupResult

logger = logging.getLogger(__name__)


def render_report(results: dict[str, GroupResult], output_dir: Path) -> None:
    """生成 JSON 原始数据 + 汇总报告。

    输出:
    - {output_dir}/safety.json, architecture.json, personalization.json
    - {output_dir}/report.json (汇总)
    """
    output_dir.mkdir(parents=True, exist_ok=True)

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

    html_path = output_dir / "report.html"
    # 报告是一次性离线生成，同步写合理。
    with html_path.open("w") as f:
        f.write(
            '<html><head><meta charset="utf-8"><title>消融实验报告</title></head><body>'
        )
        f.write("<h1>DrivePal-2 消融实验报告</h1>")
        for group_name, gr in results.items():
            f.write(f"<h2>{html.escape(group_name)} 组</h2>")
            f.write("<table border='1'>")
            for metric_name, metric_value in gr.metrics.items():
                if isinstance(metric_value, dict):
                    f.write(
                        f"<tr><td colspan='2'><b>{html.escape(metric_name)}</b></td></tr>"
                    )
                    for k, v in metric_value.items():
                        if isinstance(v, (int, float, str)):
                            f.write(
                                f"<tr><td>{html.escape(str(k))}</td><td>{html.escape(str(v))}</td></tr>"
                            )
                elif isinstance(metric_value, (int, float, str)):
                    f.write(
                        f"<tr><td>{html.escape(metric_name)}</td><td>{html.escape(str(metric_value))}</td></tr>"
                    )
            f.write("</table>")
        f.write("</body></html>")

    logger.info("报告已生成: %s", output_dir)
