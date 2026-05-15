"""检测驾驶上下文增量变化。"""

from __future__ import annotations

import copy
from dataclasses import dataclass

from app.utils import haversine

_DEFAULT_FATIGUE_DELTA = 0.1


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

    def __init__(
        self, proximity_meters: float = 500.0, fatigue_delta_threshold: float = 0.1
    ) -> None:
        """初始化 ContextMonitor。

        Args:
            proximity_meters: 位置变化判定的距离阈值（米）。
            fatigue_delta_threshold: 疲劳变化判定的增量阈值。

        """
        self._last: dict | None = None
        self._proximity_meters = proximity_meters
        self._fatigue_delta_threshold = fatigue_delta_threshold

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
            try:
                lat1 = float(old_loc.get("latitude", 0))
                lon1 = float(old_loc.get("longitude", 0))
                lat2 = float(new_loc.get("latitude", 0))
                lon2 = float(new_loc.get("longitude", 0))
                dist = haversine(lat1, lon1, lat2, lon2)
                delta.location_changed = dist > self._proximity_meters
                delta.location_proximity = dist
            except ValueError, TypeError:
                pass

        try:
            old_fatigue = float(
                self._last.get("driver_state", {}).get("fatigue_level", 0)
            )
            new_fatigue = float(ctx.get("driver_state", {}).get("fatigue_level", 0))
            delta.fatigue_increased = (
                new_fatigue > old_fatigue + self._fatigue_delta_threshold
            )
        except ValueError, TypeError:
            pass

        old_wl = self._last.get("driver_state", {}).get("workload")
        new_wl = ctx.get("driver_state", {}).get("workload")
        delta.workload_changed = old_wl != new_wl

        self._last = copy.deepcopy(ctx)
        return delta
