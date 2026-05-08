"""遗忘曲线模块，提供记忆强度衰减模型和遗忘判定。

基于 Ebbinghaus 遗忘曲线的简化实现，
通过指数衰减函数计算记忆留存率。
"""

import enum
import logging
import math
import random
from datetime import date

logger = logging.getLogger(__name__)

SOFT_FORGET_THRESHOLD = 0.15
FORGETTING_TIME_SCALE = 1


def forgetting_retention(days_elapsed: float, strength: float) -> float:
    """计算经过 days_elapsed 天后的记忆留存率。

    Args:
        days_elapsed: 距离上次回忆的天数。
        strength: 记忆强度系数，值越大衰减越慢。

    Returns:
        0~1 的留存率。

    """
    if days_elapsed <= 0:
        return 1.0
    if strength <= 0:
        return 0.0
    return math.exp(-days_elapsed / (FORGETTING_TIME_SCALE * strength))


class ForgetMode(enum.Enum):
    """遗忘策略模式。"""

    DETERMINISTIC = "deterministic"
    PROBABILISTIC = "probabilistic"


def compute_ingestion_forget_ids(
    metadata: list[dict],
    reference_date: str,
    rng: random.Random | None = None,
    mode: ForgetMode = ForgetMode.DETERMINISTIC,
) -> list[int]:
    """对 metadata 中的条目执行摄入时遗忘，返回应硬删除的 FAISS ID 列表。

    对齐 VehicleMemBench _forget_at_ingestion 行为：
    - 跳过 daily_summary 类型条目
    - 按遗忘曲线 + 记忆强度决定保留/丢弃
    - **不修改**传入的 metadata，仅返回 ID 列表

    Returns:
        应硬删除的 FAISS ID 列表。空列表表示无条目需删除。

    """
    try:
        ref_dt = date.fromisoformat(reference_date[:10])
    except ValueError, TypeError:
        logger.exception(
            "compute_ingestion_forget_ids: invalid reference_date=%r", reference_date
        )
        return []

    ids_to_remove: list[int] = []
    rng_once = rng if rng is not None else random.Random()
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
            should_forget = retention < SOFT_FORGET_THRESHOLD
        if should_forget:
            fid = entry.get("faiss_id")
            if fid is not None:
                ids_to_remove.append(fid)
    return ids_to_remove
