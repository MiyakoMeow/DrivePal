"""实验报告生成."""

import json
import logging
from pathlib import Path

from .types import GroupResult

logger = logging.getLogger(__name__)


def render_report(results: dict[str, GroupResult], run_dir: Path) -> None:
    """写全局 summary.json。"""
    summary: dict[str, object] = {}
    for name, gr in results.items():
        summary[name] = {
            "group": gr.group,
            "metrics": gr.metrics,
            "result_count": len(gr.variant_results),
            "score_count": len(gr.judge_scores),
        }
    out_path = run_dir / "summary.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    logger.info("全局总结已写入: %s", out_path)
