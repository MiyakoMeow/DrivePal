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


class ForgettingCurve:
    """管理遗忘曲线判定逻辑，控制执行频率。"""

    def __init__(
        self,
        mode: ForgetMode | None = None,
        seed: int | None = None,
    ) -> None:
        """初始化遗忘曲线，重置计时器（使用负值确保首次调用通过节流）。"""
        self._mode = mode if mode is not None else _resolve_forget_mode()
        self._rng = (
            random.Random(seed)  # noqa: S311
            if self._mode == ForgetMode.PROBABILISTIC
            else random
        )
        self._last_forget_time: float = -float(FORGET_INTERVAL_SECONDS) - 1

    def maybe_forget(
        self, metadata: list[dict], reference_date: str | None = None
    ) -> list[int]:
        """对达到遗忘阈值的条目标记 forgotten=True。

        概率模式下同时返回应硬删除的 FAISS ID 列表。

        Args:
            metadata: 记忆条目列表（会被原地修改 forgotten 标记）。
            reference_date: 参考日期，默认当天 UTC。

        Returns:
            FAISS ID 列表（概率模式返回新遗忘的 ID，确定性模式返回空列表）。

        """
        now = time.monotonic()
        if now - self._last_forget_time < FORGET_INTERVAL_SECONDS:
            return []
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

            if self._mode == ForgetMode.PROBABILISTIC:
                should_forget = self._rng.random() > retention
            else:
                should_forget = retention < SOFT_FORGET_THRESHOLD

            if should_forget:
                entry["forgotten"] = True
                if self._mode == ForgetMode.PROBABILISTIC:
                    fid = entry.get("faiss_id")
                    if fid is not None:
                        forgotten_ids.append(fid)
        return forgotten_ids
