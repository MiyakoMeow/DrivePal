"""实验报告生成."""

import json
import logging
from pathlib import Path

from experiments.ablation.types import GroupResult

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

    logger.info("报告已生成: %s", output_dir)
