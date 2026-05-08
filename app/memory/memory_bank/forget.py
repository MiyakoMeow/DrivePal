"""遗忘曲线模块，提供记忆强度衰减模型和遗忘判定。"""

import enum
import logging
import math
import random
from datetime import UTC, date, datetime, timedelta

logger = logging.getLogger(__name__)


class ForgetMode(enum.Enum):
    """遗忘策略模式。"""

    DETERMINISTIC = "deterministic"
    PROBABILISTIC = "probabilistic"


def forgetting_retention(days_elapsed: float, strength: float) -> float:
    """计算经过 days_elapsed 天后的记忆留存率。days<=0→1.0，strength<=0→0.0。"""
    if days_elapsed <= 0:
        return 1.0
    if strength <= 0:
        return 0.0
    return math.exp(-days_elapsed / strength)


def compute_forget_ids(
    metadata: list[dict],
    reference_date: str,
    *,
    mode: ForgetMode = ForgetMode.DETERMINISTIC,
    rng: random.Random | None = None,
    threshold: float = 0.15,
) -> list[int]:
    """遍历 metadata，返回应硬删除的 faiss_id 列表。跳过 daily_summary。不修改 metadata。"""
    try:
        ref_dt = date.fromisoformat(reference_date[:10])
    except ValueError, TypeError:
        logger.exception(
            "compute_forget_ids: invalid reference_date=%r", reference_date
        )
        return []

    rng_once = rng if rng is not None else random.Random()
    ids_to_remove: list[int] = []
    for entry in metadata:
        if entry.get("type") == "daily_summary":
            continue
        ts = entry.get("last_recall_date") or entry.get("timestamp", "")[:10]
        try:
            mem_dt = date.fromisoformat(ts[:10])
            days = (ref_dt - mem_dt).days
            strength = float(entry.get("memory_strength", 1))
        except ValueError, TypeError:
            continue
        retention = forgetting_retention(days, strength)
        if mode == ForgetMode.PROBABILISTIC:
            should_forget = rng_once.random() > retention
        else:
            should_forget = retention < threshold
        if should_forget:
            fid = entry.get("faiss_id")
            if fid is not None:
                ids_to_remove.append(fid)
    return ids_to_remove


def compute_reference_date(metadata: list[dict]) -> str:
    """从 metadata 时间戳推算参考日期（最大日期 +1 天）。无条目返回今天 UTC。"""
    if not metadata:
        return datetime.now(UTC).strftime("%Y-%m-%d")
    max_date: date | None = None
    for entry in metadata:
        ts = entry.get("last_recall_date") or entry.get("timestamp", "")
        try:
            d = date.fromisoformat(ts[:10])
        except ValueError, TypeError:
            continue
        if max_date is None or d > max_date:
            max_date = d
    if max_date is None:
        return datetime.now(UTC).strftime("%Y-%m-%d")
    return (max_date + timedelta(days=1)).isoformat()
