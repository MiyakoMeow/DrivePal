"""实验报告生成."""

import logging
from pathlib import Path

from ._io import write_json_atomic
from .types import GroupResult

logger = logging.getLogger(__name__)


async def render_report(results: dict[str, GroupResult], run_dir: Path) -> None:
    """异步写全局 summary.json。"""
    summary: dict[str, object] = {}
    for name, gr in results.items():
        summary[name] = {
            "group": gr.group,
            "metrics": gr.metrics,
            "result_count": len(gr.variant_results),
            "score_count": len(gr.judge_scores),
        }
    out_path = run_dir / "summary.json"
    await write_json_atomic(out_path, summary)
    logger.info("全局总结已写入: %s", out_path)
