"""GraphQL 转换函数."""

from typing import Any

from app.api.graphql_schema import (
    DriverStateGQL,
    DrivingContextGQL,
    GeoLocationGQL,
    ScenarioPresetGQL,
    SpatioTemporalContextGQL,
    TrafficConditionGQL,
)
from app.schemas.context import DrivingContext


def dict_to_gql_context(d: dict[str, Any]) -> DrivingContextGQL:
    driver_d = d.get("driver", {})
    spatial_d = d.get("spatial", {})
    traffic_d = d.get("traffic", {})
    loc = spatial_d.get("current_location", {})
    dest = spatial_d.get("destination")
    return DrivingContextGQL(
        driver=DriverStateGQL(
            emotion=driver_d.get("emotion", "neutral"),
            workload=driver_d.get("workload", "normal"),
            fatigue_level=driver_d.get("fatigue_level", 0.0),
        ),
        spatial=SpatioTemporalContextGQL(
            current_location=GeoLocationGQL(
                latitude=loc.get("latitude", 0.0),
                longitude=loc.get("longitude", 0.0),
                address=loc.get("address", ""),
                speed_kmh=loc.get("speed_kmh", 0.0),
            ),
            destination=GeoLocationGQL(
                latitude=dest.get("latitude", 0.0),
                longitude=dest.get("longitude", 0.0),
                address=dest.get("address", ""),
                speed_kmh=dest.get("speed_kmh", 0.0),
            )
            if dest
            else None,
            eta_minutes=spatial_d.get("eta_minutes"),
            heading=spatial_d.get("heading"),
        ),
        traffic=TrafficConditionGQL(
            congestion_level=traffic_d.get("congestion_level", "smooth"),
            incidents=traffic_d.get("incidents", []),
            estimated_delay_minutes=traffic_d.get("estimated_delay_minutes", 0),
        ),
        scenario=d.get("scenario", "parked"),
    )


def preset_dict_to_gql(p: dict[str, Any]) -> ScenarioPresetGQL:
    ctx_raw = p.get("context", {})
    safe = {k: v for k, v in ctx_raw.items() if k in DrivingContext.model_fields}
    sp = safe.get("spatial", {})
    if isinstance(sp, dict):
        for key in ("destination", "eta_minutes", "heading"):
            if sp.get(key) == "":
                sp[key] = None
    ctx = DrivingContext(**safe)
    return ScenarioPresetGQL(
        id=p.get("id", ""),
        name=p.get("name", ""),
        context=dict_to_gql_context(ctx.model_dump()),
        created_at=p.get("created_at", ""),
    )
