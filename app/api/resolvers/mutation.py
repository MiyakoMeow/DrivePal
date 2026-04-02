"""Mutation resolvers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal, cast

import strawberry
from graphql.error import GraphQLError

from app.api.graphql_schema import (
    DrivingContextGQL,
    DrivingContextInput,
    DriverStateGQL,
    FeedbackInput,
    FeedbackResult,
    GeoLocationGQL,
    JSON,
    ProcessQueryInput,
    ProcessQueryResult,
    ScenarioPresetGQL,
    ScenarioPresetInput,
    SpatioTemporalContextGQL,
    TrafficConditionGQL,
    WorkflowStagesGQL,
)
from app.memory.schemas import FeedbackData
from app.memory.types import MemoryMode
from app.schemas.context import (
    DriverState,
    DrivingContext,
    GeoLocation,
    ScenarioPreset,
    TrafficCondition,
)
from app.storage.toml_store import TOMLStore

logger = logging.getLogger(__name__)


def _preset_store() -> TOMLStore:
    from app.api.main import DATA_DIR

    return TOMLStore(DATA_DIR, Path("scenario_presets.toml"), list)


def _input_to_context_dict(input_obj: DrivingContextInput) -> dict[str, Any]:
    result: dict[str, Any] = {
        "scenario": input_obj.scenario,
        "driver": {},
        "spatial": {},
        "traffic": {},
    }
    if input_obj.driver:
        result["driver"] = {
            "emotion": input_obj.driver.emotion,
            "workload": input_obj.driver.workload,
            "fatigue_level": input_obj.driver.fatigue_level,
        }
    if input_obj.spatial:
        spatial: dict[str, Any] = {
            "current_location": {
                "latitude": input_obj.spatial.current_location.latitude,
                "longitude": input_obj.spatial.current_location.longitude,
                "address": input_obj.spatial.current_location.address,
                "speed_kmh": input_obj.spatial.current_location.speed_kmh,
            },
        }
        if input_obj.spatial.destination:
            spatial["destination"] = {
                "latitude": input_obj.spatial.destination.latitude,
                "longitude": input_obj.spatial.destination.longitude,
                "address": input_obj.spatial.destination.address,
                "speed_kmh": input_obj.spatial.destination.speed_kmh,
            }
        if input_obj.spatial.eta_minutes is not None:
            spatial["eta_minutes"] = input_obj.spatial.eta_minutes
        if input_obj.spatial.heading is not None:
            spatial["heading"] = input_obj.spatial.heading
        result["spatial"] = spatial
    if input_obj.traffic:
        result["traffic"] = {
            "congestion_level": input_obj.traffic.congestion_level,
            "incidents": input_obj.traffic.incidents,
            "estimated_delay_minutes": input_obj.traffic.estimated_delay_minutes,
        }
    return result


def _dict_to_gql_context(d: dict[str, Any]) -> DrivingContextGQL:
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


def _to_gql_preset(p: dict[str, Any]) -> ScenarioPresetGQL:
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
        context=_dict_to_gql_context(ctx.model_dump()),
        created_at=p.get("created_at", ""),
    )


@strawberry.type
class Mutation:
    """GraphQL Mutation 集合."""

    @strawberry.mutation
    async def process_query(self, input: ProcessQueryInput) -> ProcessQueryResult:
        """处理用户查询并返回工作流结果."""
        from app.api.main import DATA_DIR, get_memory_module
        from app.agents.workflow import AgentWorkflow

        try:
            mm = get_memory_module()
            workflow = AgentWorkflow(
                data_dir=DATA_DIR,
                memory_mode=MemoryMode(input.memory_mode.value),
                memory_module=mm,
            )

            driving_context = None
            if input.context:
                driving_context = _input_to_context_dict(input.context)

            result, event_id, stages = await workflow.run_with_stages(
                input.query, driving_context
            )
            return ProcessQueryResult(
                result=result,
                event_id=event_id,
                stages=WorkflowStagesGQL(
                    context=cast("JSON", stages.context),
                    task=cast("JSON", stages.task),
                    decision=cast("JSON", stages.decision),
                    execution=cast("JSON", stages.execution),
                ),
            )
        except Exception as e:
            logger.exception("processQuery failed: %s", e)
            raise GraphQLError("Internal server error")

    @strawberry.mutation
    async def submit_feedback(self, input: FeedbackInput) -> FeedbackResult:
        """提交用户反馈."""
        if input.action not in ("accept", "ignore"):
            raise GraphQLError(
                f"Invalid action: {input.action!r}. Must be 'accept' or 'ignore'"
            )
        from app.api.main import get_memory_module

        try:
            mm = get_memory_module()
            safe_action: Literal["accept", "ignore"]
            safe_action = "accept" if input.action == "accept" else "ignore"
            feedback = FeedbackData(
                action=safe_action,
                modified_content=input.modified_content,
            )
            await mm.update_feedback(input.event_id, feedback)
            return FeedbackResult(status="success")
        except Exception as e:
            logger.exception("submitFeedback failed: %s", e)
            raise GraphQLError("Internal server error")

    @strawberry.mutation
    async def save_scenario_preset(
        self, input: ScenarioPresetInput
    ) -> ScenarioPresetGQL:
        """保存场景预设."""
        store = _preset_store()
        preset = ScenarioPreset(name=input.name)
        if input.context:
            ctx_dict = _input_to_context_dict(input.context)
            preset.context = DrivingContext()
            if "driver" in ctx_dict and ctx_dict["driver"]:
                preset.context.driver = DriverState(**ctx_dict["driver"])
            if "spatial" in ctx_dict and ctx_dict["spatial"]:
                sp = ctx_dict["spatial"]
                preset.context.spatial.current_location = GeoLocation(
                    **sp.get("current_location", {})
                )
                if sp.get("destination"):
                    preset.context.spatial.destination = GeoLocation(
                        **sp["destination"]
                    )
                if sp.get("eta_minutes") is not None:
                    preset.context.spatial.eta_minutes = sp["eta_minutes"]
                if sp.get("heading") is not None:
                    preset.context.spatial.heading = sp["heading"]
            if "traffic" in ctx_dict and ctx_dict["traffic"]:
                preset.context.traffic = TrafficCondition(**ctx_dict["traffic"])
            preset.context.scenario = ctx_dict.get("scenario", "parked")
        await store.append(preset.model_dump())
        return _to_gql_preset(preset.model_dump())

    @strawberry.mutation
    async def delete_scenario_preset(self, preset_id: str) -> bool:
        """删除场景预设."""
        store = _preset_store()
        presets = await store.read()
        new_presets = [p for p in presets if p.get("id") != preset_id]
        if len(new_presets) == len(presets):
            return False
        await store.write(new_presets)
        return True
