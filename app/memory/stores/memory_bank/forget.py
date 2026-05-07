"""遗忘曲线模块，提供记忆强度衰减模型和遗忘判定。

基于 Ebbinghaus 遗忘曲线的简化实现，
通过指数衰减函数计算记忆留存率。
"""

import enum
import math
import os
import random
import time
from datetime import UTC, date, datetime

SOFT_FORGET_THRESHOLD = 0.15
FORGET_INTERVAL_SECONDS = 300
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


def _resolve_forget_mode() -> ForgetMode:
    """从环境变量 MEMORYBANK_FORGET_MODE 解析遗忘模式。"""
    mode = os.getenv("MEMORYBANK_FORGET_MODE", "deterministic").lower()
    if mode == "probabilistic":
        return ForgetMode.PROBABILISTIC
    return ForgetMode.DETERMINISTIC


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
        ref_dt = datetime.strptime(reference_date[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        logger.error(
            "compute_ingestion_forget_ids: invalid reference_date=%r", reference_date
        )
        return []

    ids_to_remove: list[int] = []
    for entry in metadata:
        if entry.get("type") == "daily_summary":
            continue
        ts = entry.get("last_recall_date") or entry.get("timestamp", "")[:10]
        try:
            mem_dt = datetime.strptime(ts[:10], "%Y-%m-%d").date()
            days = (ref_dt - mem_dt).days
            strength = float(entry.get("memory_strength", 1))
        except (ValueError, TypeError):
            continue
        retention = forgetting_retention(days, strength)
        if mode == ForgetMode.PROBABILISTIC:
            local_rng = rng if rng is not None else random.Random()
            should_forget = local_rng.random() > retention
        else:
            should_forget = retention < SOFT_FORGET_THRESHOLD
        if should_forget:
            fid = entry.get("faiss_id")
            if fid is not None:
                ids_to_remove.append(fid)
    return ids_to_remove


class ForgettingCurve:
    """管理遗忘曲线判定逻辑，控制执行频率。"""

    def __init__(
        self,
        mode: ForgetMode | None = None,
        seed: int | None = None,
        rng: random.Random | None = None,
    ) -> None:
        """初始化遗忘曲线，重置计时器（使用负值确保首次调用通过节流）。

        Args:
            mode: 遗忘策略模式。
            seed: 随机种子（与 rng 互斥；仅 mode=PROBABILISTIC 时使用）。
            rng: 外部 RNG 实例（与 seed 互斥；优先级高于 seed）。

        """
        self._mode = mode if mode is not None else _resolve_forget_mode()
        if rng is not None:
            self._rng = rng
        else:
            self._rng = (
                random.Random(seed) if self._mode == ForgetMode.PROBABILISTIC else None
            )
        self._last_forget_time: float = -float(FORGET_INTERVAL_SECONDS) - 1

    def maybe_forget(
        self, metadata: list[dict], reference_date: str | None = None
    ) -> list[int] | None:
        """对达到遗忘阈值的条目标记 forgotten=True。

        概率模式下同时返回应硬删除的 FAISS ID 列表。

        Args:
            metadata: 记忆条目列表（会被原地修改 forgotten 标记）。
            reference_date: 参考日期，默认当天 UTC。

        Returns:
            None 当节流（未执行）；FAISS ID 列表（概率模式返回新遗忘的 ID，
            确定性模式返回空列表）。

        """
        now = time.monotonic()
        if now - self._last_forget_time < FORGET_INTERVAL_SECONDS:
            return None
        self._last_forget_time = now
        today = reference_date or datetime.now(UTC).strftime("%Y-%m-%d")
        forgotten_ids: list[int] = []
        for entry in metadata:
            if entry.get("type") == "daily_summary":
                continue
            if entry.get("forgotten"):
                continue
            ts = entry.get("last_recall_date") or entry.get("timestamp", "")[:10]
            strength = entry.get("memory_strength", 1)
            try:
                days = (
                    date.fromisoformat(today[:10]) - date.fromisoformat(ts[:10])
                ).days
                strength_float = float(strength)
            except ValueError, TypeError:
                continue
            retention = forgetting_retention(days, strength_float)

            if self._rng is not None:
                should_forget = self._rng.random() > retention
            else:
                should_forget = retention < SOFT_FORGET_THRESHOLD

            if should_forget:
                entry["forgotten"] = True
                if self._rng is not None:
                    fid = entry.get("faiss_id")
                    if fid is not None:
                        forgotten_ids.append(fid)
        return forgotten_ids
