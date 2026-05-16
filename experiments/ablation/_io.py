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

from app.agents.rules import get_fatigue_threshold as _get_fatigue_threshold

from .types import Variant, VariantResult

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from .types import GroupResult, JudgeScores

logger = logging.getLogger(__name__)

try:
    VARIANT_TIMEOUT_SECONDS = int(os.getenv("ABLATION_VARIANT_TIMEOUT_SECONDS", "300"))
except ValueError:
    VARIANT_TIMEOUT_SECONDS = 300
"""单变体执行超时（秒）。ablation_runner + personalization_group 共用。"""

JUDGE_TIMEOUT_SECONDS = 120
"""Judge 单次评分超时（秒）。judge.py 共用。"""


def get_fatigue_threshold() -> float:
    """安全读取 FATIGUE_THRESHOLD 环境变量，解析失败回退默认 0.7。

    architecture_group / safety_group / scenario_synthesizer 共用此单点。
    薄封装 app.agents.rules.get_fatigue_threshold()——规则引擎是权威源。
    """
    return _get_fatigue_threshold()


def safe_event_id(record: dict[str, Any]) -> str | None:
    """从 JSON dict 安全读取 event_id，过滤非法类型。"""
    eid = record.get("event_id")
    return eid if isinstance(eid, (str, type(None))) else None


def variant_result_from_dict(d: dict[str, Any]) -> VariantResult:
    """从 JSON dict 重建 VariantResult，兼容旧 checkpoint 缺失字段。"""
    return VariantResult(
        scenario_id=str(d["scenario_id"]),
        variant=Variant(d["variant"]),
        decision=d.get("decision", {}),
        result_text=d.get("result_text") or "",
        event_id=safe_event_id(d),
        stages=d.get("stages", {}),
        latency_ms=d.get("latency_ms", 0),
        modifications=d.get("modifications", []),
        round_index=d.get("round_index", 0),
    )


async def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    """异步原子写 JSON。先写临时文件，成功后再 rename 覆盖。

    含序列化降级容错：遇不可序列化值（如自定义类型）用 str() 兜底。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        async with aiofiles.open(tmp_path, "w", encoding="utf-8") as f:
            try:
                await f.write(json.dumps(data, ensure_ascii=False, indent=2))
            except (TypeError, ValueError) as e:
                logger.warning("JSON 序列化失败（%s），降级写入", e)
                await f.write(
                    json.dumps(data, ensure_ascii=False, indent=2, default=str)
                )
        tmp_path.replace(path)
    except OSError:
        logger.exception("原子写 JSON 失败: %s", path)
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise


async def write_summary(path: Path, data: dict[str, Any]) -> None:
    """写 JSON 总结文件。timestamp 始终由系统生成，覆盖 data 中同名键。"""
    record: dict[str, Any] = {
        **data,
        "timestamp": datetime.now(tz=UTC).isoformat(),
    }
    await write_json_atomic(path, record)


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
    config: dict[str, Any] = {
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "cli_args": {k: getattr(args, k, None) for k in cli_keys},
        "environment": {k: os.environ.get(k, None) for k in env_keys},
    }
    await write_json_atomic(path, config)


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


async def write_scores_json(path: Path, scores: list[JudgeScores]) -> None:
    """写入 Judge 评分文件。全量运行和 judge-only 共用。"""
    data: dict[str, Any] = {
        "scores": [
            {
                "scenario_id": s.scenario_id,
                "variant": s.variant.value,
                "safety_score": s.safety_score,
                "reasonableness_score": s.reasonableness_score,
                "overall_score": s.overall_score,
                "violation_flags": s.violation_flags,
            }
            for s in scores
        ]
    }
    await write_json_atomic(path, data)


async def load_checkpoint(
    path: Path,
) -> tuple[set[tuple[str, str]], list[VariantResult], dict | None]:
    """读取 JSONL checkpoint。

    Returns:
        (已完成的(scenario_id,variant)集合, VariantResult 列表, 最后一条 extra 状态 | None)
        extra 为 feedback_simulator.export_state() 序列化结果，无时返回 None。

    """
    ids: set[tuple[str, str]] = set()
    results: list[VariantResult] = []
    last_extra: dict | None = None
    try:
        async with aiofiles.open(path, encoding="utf-8") as f:
            async for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    d = json.loads(stripped)
                    ids.add((d["scenario_id"], d["variant"]))
                    results.append(variant_result_from_dict(d))
                    if "extra" in d and isinstance(d["extra"], dict):
                        last_extra = d["extra"]
                except json.JSONDecodeError, KeyError, ValueError:
                    logger.warning("跳过无效 checkpoint 行: %s", stripped[:80])
                    continue
    except FileNotFoundError:
        logger.warning("Checkpoint 文件不存在（%s），从零开始运行", path)
        return ids, results, None
    except OSError:
        logger.warning("Checkpoint 读取失败（%s），从零开始运行", path)
        # 中途 I/O 错误——丢弃部分数据，避免不一致结果混入续跑
        return set(), [], None
    return ids, results, last_extra


async def append_checkpoint(
    path: Path,
    vr: VariantResult,
    *,
    include_modifications: bool = False,
    extra: dict | None = None,
) -> None:
    """追加写单条 VariantResult 到 checkpoint JSONL。extra 为可选的附加状态 dict。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    record: dict[str, object] = {
        "scenario_id": vr.scenario_id,
        "variant": vr.variant.value,
        "decision": vr.decision,
        "stages": vr.stages,
        "latency_ms": vr.latency_ms,
        "round_index": vr.round_index,
        "result_text": vr.result_text,
        "event_id": vr.event_id,
    }
    if include_modifications:
        record["modifications"] = vr.modifications
    if extra:
        record["extra"] = extra
    async with aiofiles.open(path, "a", encoding="utf-8") as f:
        await f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


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
                    "result_text": r.result_text,
                    "event_id": r.event_id,
                }
                if include_modifications:
                    record["modifications"] = r.modifications
                await f.write(
                    json.dumps(record, ensure_ascii=False, default=str) + "\n"
                )
        tmp_path.replace(path)
    except OSError:
        logger.exception("JSONL 写入失败: %s", path)
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise
