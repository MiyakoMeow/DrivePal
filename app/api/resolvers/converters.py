"""Strawberry ↔ Pydantic 类型转换工具."""

import dataclasses
from enum import Enum
from pathlib import Path
from typing import Any, cast

from app.api.graphql_schema import (
    DriverStateGQL,
    DrivingContextGQL,
    DrivingContextInput,
    GeoLocationGQL,
    ScenarioPresetGQL,
    SpatioTemporalContextGQL,
    TrafficConditionGQL,
)
from app.config import DATA_DIR
from app.schemas.context import DrivingContext
from app.storage.toml_store import TOMLStore


def strawberry_to_plain(obj: object) -> object:
    """递归将 Strawberry 类型转普通 Python 对象（Enum→.value，dataclass→dict）。

    跳过 None 值字段，避免 Pydantic 对非 Optional 字段收到 None 引发验证错误。
    结果可直接喂给 Pydantic model_validate。
    """
    if obj is None or isinstance(obj, (str, bytes, int, float, bool)):
        return obj
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, list):
        return [strawberry_to_plain(item) for item in obj]
    if dataclasses.is_dataclass(obj):
        return {
            f.name: strawberry_to_plain(getattr(obj, f.name))
            for f in dataclasses.fields(obj)
            if getattr(obj, f.name) is not None
        }
    return obj


def input_to_context(input_obj: DrivingContextInput) -> DrivingContext:
    """将 Strawberry GraphQL input 转为 Pydantic DrivingContext。"""
    data = cast("dict[str, Any]", strawberry_to_plain(input_obj))
    return DrivingContext.model_validate(
        {k: v for k, v in data.items() if v is not None},
    )


def dict_to_gql_context(d: dict[str, Any]) -> DrivingContextGQL:
    """将 dict 转为 DrivingContextGQL（通过 Pydantic 验证后手工构造）。

    注意：P3 实施后此函数被 DrivingContextGQL.from_pydantic() 替代。
    """
    ctx = DrivingContext.model_validate(d)
    dest = ctx.spatial.destination
    return DrivingContextGQL(
        driver=DriverStateGQL(
            emotion=ctx.driver.emotion,
            workload=ctx.driver.workload,
            fatigue_level=ctx.driver.fatigue_level,
        ),
        spatial=SpatioTemporalContextGQL(
            current_location=GeoLocationGQL(
                latitude=ctx.spatial.current_location.latitude,
                longitude=ctx.spatial.current_location.longitude,
                address=ctx.spatial.current_location.address,
                speed_kmh=ctx.spatial.current_location.speed_kmh,
            ),
            destination=GeoLocationGQL(
                latitude=dest.latitude,
                longitude=dest.longitude,
                address=dest.address,
                speed_kmh=dest.speed_kmh,
            )
            if dest is not None
            else None,
            eta_minutes=ctx.spatial.eta_minutes,
            heading=ctx.spatial.heading,
        ),
        traffic=TrafficConditionGQL(
            congestion_level=ctx.traffic.congestion_level,
            incidents=ctx.traffic.incidents,
            estimated_delay_minutes=ctx.traffic.estimated_delay_minutes,
        ),
        scenario=ctx.scenario,
    )


def preset_store() -> TOMLStore:
    """获取场景预设存储实例。"""
    return TOMLStore(DATA_DIR, Path("scenario_presets.toml"), list)


def to_gql_preset(p: dict[str, Any]) -> ScenarioPresetGQL:
    """将存储 dict 转为 ScenarioPresetGQL。"""
    ctx_raw = p.get("context", {})
    safe = {k: v for k, v in ctx_raw.items() if k in DrivingContext.model_fields}
    sp = safe.get("spatial", {})
    if isinstance(sp, dict):
        # TOML 存储将 None 转空字符串，读取时恢复
        for key in ("destination", "eta_minutes", "heading"):
            if sp.get(key) == "":
                sp[key] = None
    ctx = DrivingContext.model_validate(safe)
    return ScenarioPresetGQL(
        id=p.get("id", ""),
        name=p.get("name", ""),
        context=dict_to_gql_context(ctx.model_dump()),
        created_at=p.get("created_at", ""),
    )
