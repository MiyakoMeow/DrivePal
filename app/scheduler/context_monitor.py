"""检测驾驶上下文增量变化。"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass

_FATIGUE_DELTA_THRESHOLD = 0.1


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """返回两点间距离（米）。"""
    earth_radius_m = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    )
    return earth_radius_m * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@dataclass
class ContextDelta:
    """驾驶上下文增量变化。"""

    scenario_changed: bool = False
    location_changed: bool = False
    location_proximity: float | None = None
    fatigue_increased: bool = False
    workload_changed: bool = False


class ContextMonitor:
    """监测驾驶上下文增量变化。"""

    def __init__(self, proximity_meters: float = 500.0) -> None:
        """初始化 ContextMonitor。

        Args:
            proximity_meters: 位置变化判定的距离阈值（米）。

        """
        self._last: dict | None = None
        self._proximity_meters = proximity_meters

    def update(self, ctx: dict) -> ContextDelta:
        """更新上下文并返回增量变化。首次调用返回空 delta。"""
        delta = ContextDelta()
        if self._last is None:
            self._last = copy.deepcopy(ctx)
            return delta

        old_scenario = self._last.get("scenario")
        new_scenario = ctx.get("scenario")
        delta.scenario_changed = bool(old_scenario) and old_scenario != new_scenario

        old_loc = self._last.get("spatial", {}).get("current_location", {})
        new_loc = ctx.get("spatial", {}).get("current_location", {})
        if old_loc and new_loc:
            dist = _haversine(
                float(old_loc.get("latitude", 0)),
                float(old_loc.get("longitude", 0)),
                float(new_loc.get("latitude", 0)),
                float(new_loc.get("longitude", 0)),
            )
            delta.location_changed = dist > self._proximity_meters
            delta.location_proximity = dist

        old_fatigue = self._last.get("driver_state", {}).get("fatigue_level", 0)
        new_fatigue = ctx.get("driver_state", {}).get("fatigue_level", 0)
        delta.fatigue_increased = new_fatigue > old_fatigue + _FATIGUE_DELTA_THRESHOLD

        old_wl = self._last.get("driver_state", {}).get("workload")
        new_wl = ctx.get("driver_state", {}).get("workload")
        delta.workload_changed = old_wl != new_wl

        self._last = copy.deepcopy(ctx)
        return delta
