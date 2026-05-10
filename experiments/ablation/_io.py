"""共享 I/O 工具.

TYPE_CHECKING 仅用于类型注解导入——Python 3.14 PEP 649 默认延迟注解求值，
故 Path 和 VariantResult 无需运行时导入。
"""

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
    """将 VariantResult 列表写入 JSONL。先写临时文件，成功后再 rename 覆盖。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        async with aiofiles.open(tmp_path, "w", encoding="utf-8") as f:
            for r in results:
                record: dict[str, Any] = {
                    "scenario_id": r.scenario_id,
                    "variant": r.variant.value,
                    "decision": r.decision,
                    "stages": r.stages,
                    "latency_ms": r.latency_ms,
                    "round_index": r.round_index,
                }
                if include_modifications:
                    record["modifications"] = r.modifications
                await f.write(json.dumps(record, ensure_ascii=False) + "\n")
        tmp_path.replace(path)
    except OSError:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise
