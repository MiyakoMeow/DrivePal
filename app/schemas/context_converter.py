"""DrivingContextInput → dict 转换。"""

from typing import Any


def _v(val: Any) -> Any:
    return val.value if hasattr(val, "value") else val


def _geo_to_dict(loc: Any) -> dict[str, Any]:
    return {
        "latitude": loc.latitude,
        "longitude": loc.longitude,
        "address": loc.address,
        "speed_kmh": loc.speed_kmh,
    }


def input_to_context_dict(input_obj: Any) -> dict[str, Any]:
    """将 DrivingContextInput 实例转为 context dict（DrivingContext 兼容字段名）。"""
    result: dict[str, Any] = {
        "scenario": _v(input_obj.scenario),
        "driver": {},
        "spatial": {},
        "traffic": {},
    }

    if driver := getattr(input_obj, "driver", None):
        d = {
            "emotion": _v(driver.emotion),
            "workload": _v(driver.workload),
            "fatigue_level": driver.fatigue_level,
        }
        result["driver"] = {k: v for k, v in d.items() if v is not None}

    if spatial := getattr(input_obj, "spatial", None):
        spatial_dict: dict[str, Any] = {}
        if spatial.current_location:
            spatial_dict["current_location"] = _geo_to_dict(spatial.current_location)
        if spatial.destination:
            spatial_dict["destination"] = _geo_to_dict(spatial.destination)
        if spatial.eta_minutes is not None:
            spatial_dict["eta_minutes"] = spatial.eta_minutes
        if spatial.heading is not None:
            spatial_dict["heading"] = spatial.heading
        result["spatial"] = spatial_dict

    if traffic := getattr(input_obj, "traffic", None):
        t = {
            "congestion_level": _v(traffic.congestion_level),
            "incidents": traffic.incidents,
            "estimated_delay_minutes": traffic.estimated_delay_minutes,
        }
        result["traffic"] = {k: v for k, v in t.items() if v is not None}

    return result
