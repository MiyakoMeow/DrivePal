"""Strawberry ↔ Pydantic 类型转换工具."""

import dataclasses
from enum import Enum
from pathlib import Path
from typing import Any, cast

from app.api.graphql_schema import (
    DrivingContextGQL,
    DrivingContextInput,
    ScenarioPresetGQL,
)
from app.config import DATA_DIR
from app.schemas.context import DrivingContext
from app.storage.toml_store import TOMLStore

_PRESETS_FILENAME = "scenario_presets.toml"


def strawberry_to_plain(obj: object) -> object:
    """递归将 Strawberry 类型转普通 Python 对象（Enum→.value，dataclass→dict）。

    跳过 None 值字段，避免 Pydantic 对非 Optional 字段收到 None 引发验证错误。
    结果可直接喂给 Pydantic model_validate。
    """
    if obj is None or isinstance(obj, (str, int, float, bool)):
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
    """将 dict 转为 DrivingContextGQL（通过 Pydantic→from_pydantic）。"""
    ctx = DrivingContext.model_validate(d)
    return DrivingContextGQL.from_pydantic(ctx)


def preset_store() -> TOMLStore:
    """获取场景预设存储实例。"""
    return TOMLStore(DATA_DIR, Path(_PRESETS_FILENAME), list)


def to_gql_preset(p: dict[str, Any]) -> ScenarioPresetGQL:
    """将存储 dict 转为 ScenarioPresetGQL。"""
    ctx_raw = p.get("context", {})
    safe = {k: v for k, v in ctx_raw.items() if k in DrivingContext.model_fields}
    sp = safe.get("spatial", {})
    if isinstance(sp, dict):
        # TOML 不支持 None，TOMLStore._clean_for_toml 已将 None 序列化为空字符串，
        # 此处反向还原，恢复 Pydantic Optional 字段的 None 语义。
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
