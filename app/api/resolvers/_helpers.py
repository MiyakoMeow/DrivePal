"""GraphQL resolver 共享工具模块."""

import dataclasses
import logging
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from graphql.error import GraphQLError

if TYPE_CHECKING:
    from collections.abc import Awaitable

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

logger = logging.getLogger(__name__)


class InternalServerError(GraphQLError):
    """内部服务器错误."""

    def __init__(self) -> None:
        super().__init__("Internal server error")


class GraphQLInvalidActionError(GraphQLError):
    """无效的操作类型."""

    def __init__(self, action: str) -> None:
        super().__init__(f"Invalid action: {action!r}")


class GraphQLEventNotFoundError(GraphQLError):
    """事件不存在."""

    def __init__(self, event_id: str) -> None:
        super().__init__(f"Event not found: {event_id!r}")


async def _safe_memory_call[T](
    coro: Awaitable[T],
    context_msg: str,
) -> T:
    try:
        return await coro
    except GraphQLError:
        raise
    except OSError as e:
        msg = "Internal storage error"
        logger.exception("%s failed", context_msg)
        raise GraphQLError(msg) from e
    except RuntimeError as e:
        msg = "Internal runtime error"
        logger.exception("%s failed", context_msg)
        raise GraphQLError(msg) from e
    except ValueError as e:
        msg = f"Invalid data in {context_msg}"
        logger.exception("%s failed", context_msg)
        raise GraphQLError(msg) from e
    except Exception as e:
        logger.exception("%s failed", context_msg)
        raise InternalServerError from e


def _preset_store() -> TOMLStore:
    return TOMLStore(DATA_DIR, Path("scenario_presets.toml"), list)


def _strawberry_to_plain(obj: object) -> object:
    if obj is None or isinstance(obj, (str, bytes, int, float, bool)):
        return obj
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, list):
        return [_strawberry_to_plain(item) for item in obj]
    if dataclasses.is_dataclass(obj):
        return {
            f.name: _strawberry_to_plain(getattr(obj, f.name))
            for f in dataclasses.fields(obj)
            if getattr(obj, f.name) is not None
        }
    msg = f"Unsupported type in _strawberry_to_plain: {type(obj).__name__}"
    raise TypeError(msg)


def _input_to_context(input_obj: DrivingContextInput) -> DrivingContext:
    data = cast("dict[str, Any]", _strawberry_to_plain(input_obj))
    return DrivingContext.model_validate(
        {k: v for k, v in data.items() if v is not None},
    )


def _dict_to_gql_context(d: dict[str, Any]) -> DrivingContextGQL:
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


def _to_gql_preset(p: dict[str, Any]) -> ScenarioPresetGQL:
    ctx_raw = p.get("context", {})
    safe = {k: v for k, v in ctx_raw.items() if k in DrivingContext.model_fields}
    sp = safe.get("spatial", {})
    if isinstance(sp, dict):
        for key in ("destination", "eta_minutes", "heading"):
            if sp.get(key) == "":
                sp[key] = None
    ctx = DrivingContext.model_validate(safe)
    return ScenarioPresetGQL(
        id=p.get("id", ""),
        name=p.get("name", ""),
        context=_dict_to_gql_context(ctx.model_dump()),
        created_at=p.get("created_at", ""),
    )
