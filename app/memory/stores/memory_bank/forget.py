"""遗忘曲线模块，提供记忆强度衰减模型和遗忘判定。

基于 Ebbinghaus 遗忘曲线的简化实现，
通过指数衰减函数计算记忆留存率。
"""

import math
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
    if days_elapsed <= 0 or strength <= 0:
        return 1.0 if days_elapsed <= 0 else 0.0
    return math.exp(-days_elapsed / (FORGETTING_TIME_SCALE * strength))


class ForgettingCurve:
    """管理遗忘曲线判定逻辑，控制执行频率。"""

    def __init__(self) -> None:
        """初始化遗忘曲线，重置计时器。"""
        self._last_forget_time: float = 0.0

    def maybe_forget(
        self, metadata: list[dict], reference_date: str | None = None
    ) -> list[dict]:
        """对 metadata 中达到遗忘阈值的条目标记 forgotten=True。

        Args:
            metadata: 记忆条目列表（会被原地修改）。
            reference_date: 参考日期，默认当天 UTC。

        Returns:
            原地修改后的 metadata。

        """
        now = time.monotonic()
        if now - self._last_forget_time < FORGET_INTERVAL_SECONDS:
            return metadata
        self._last_forget_time = now
        today = reference_date or datetime.now(UTC).strftime("%Y-%m-%d")
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
            if retention < SOFT_FORGET_THRESHOLD:
                entry["forgotten"] = True
        return metadata
