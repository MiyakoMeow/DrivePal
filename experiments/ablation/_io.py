"""共享 I/O 工具.

TYPE_CHECKING 仅用于类型注解导入——Python 3.14 PEP 649 默认延迟注解求值，
故 Path 等类型无需运行时导入。
"""

import json
import logging
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import aiofiles

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from .types import GroupResult, VariantResult

logger = logging.getLogger(__name__)


async def _write_json_async(path: Path, data: dict[str, object]) -> None:
    """异步写 JSON 到文件——含序列化降级容错。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        try:
            await f.write(json.dumps(data, ensure_ascii=False, indent=2))
        except (TypeError, ValueError) as e:
            logger.warning("JSON 序列化失败（%s），降级写入", e)
            await f.write(json.dumps(data, ensure_ascii=False, indent=2, default=str))


async def write_summary(path: Path, data: dict[str, object]) -> None:
    """写 JSON 总结文件。包含 timestamp + 状态。"""
    record: dict[str, object] = {
        "timestamp": datetime.now(tz=UTC).isoformat(),
        **data,
    }
    await _write_json_async(path, record)


async def write_config(path: Path, args: argparse.Namespace) -> None:
    """写运行配置快照——CLI 参数 + 相关环境变量。"""
    env_keys = [
        "ABLATION_SEED",
        "FATIGUE_THRESHOLD",
        "PROBABILISTIC_INFERENCE_ENABLED",
        "MEMORYBANK_SEED",
        "MEMORYBANK_FORGET_MODE",
        "MEMORYBANK_ENABLE_FORGETTING",
        "JUDGE_MODEL",
        "JUDGE_BASE_URL",
    ]
    cli_keys = (
        "data_dir",
        "group",
        "seed",
        "synthesize_only",
        "judge_only",
        "run_id",
    )
    config: dict[str, object] = {
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "cli_args": {k: getattr(args, k, None) for k in cli_keys},
        "environment": {k: os.environ.get(k, None) for k in env_keys},
    }
    await _write_json_async(path, config)


async def write_step_summary(
    path: Path,
    group_result: GroupResult,
    *,
    duration_seconds: float,
) -> None:
    """写一组实验的步骤总结。"""
    await write_summary(
        path,
        {
            "group": group_result.group,
            "status": "completed",
            "scenarios_count": len(
                {r.scenario_id for r in group_result.variant_results}
            ),
            "variants": sorted({r.variant.value for r in group_result.variant_results}),
            "total_results": len(group_result.variant_results),
            "judge_scores_count": len(group_result.judge_scores),
            "duration_seconds": round(duration_seconds, 1),
            "metrics": group_result.metrics,
        },
    )


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
