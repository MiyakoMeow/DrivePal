"""共享 I/O 工具."""

import json
from typing import TYPE_CHECKING, Any

import aiofiles

if TYPE_CHECKING:
    from pathlib import Path

    from .types import VariantResult


async def dump_variant_results_jsonl(
    path: Path,
    results: list[VariantResult],
    *,
    include_modifications: bool = False,
) -> None:
    """将 VariantResult 列表写入 JSONL。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(path, "w") as f:
        for r in results:
            record: dict[str, Any] = {
                "scenario_id": r.scenario_id,
                "variant": r.variant.value,
                "decision": r.decision,
                "stages": r.stages,
                "latency_ms": r.latency_ms,
            }
            if include_modifications:
                record["modifications"] = r.modifications
            await f.write(json.dumps(record, ensure_ascii=False) + "\n")
