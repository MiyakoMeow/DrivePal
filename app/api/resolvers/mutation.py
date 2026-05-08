"""Mutation 解析器."""

import logging
from pathlib import Path
from typing import Annotated, Any, Literal, cast

import strawberry
from graphql.error import GraphQLError

from app.agents.workflow import AgentWorkflow
from app.api.graphql_schema import (
    DriverStateGQL,
    DrivingContextGQL,
    DrivingContextInput,
    FeedbackInput,
    FeedbackResult,
    GeoLocationGQL,
    ProcessQueryInput,
    ProcessQueryResult,
    ScenarioPresetGQL,
    ScenarioPresetInput,
    SpatioTemporalContextGQL,
    TrafficConditionGQL,
    WorkflowStagesGQL,
)
from app.config import DATA_DIR
from app.memory.schemas import FeedbackData
from app.memory.singleton import get_memory_module
from app.memory.types import MemoryMode
from app.schemas.context import (
    DrivingContext,
    ScenarioPreset,
)
from app.storage.toml_store import TOMLStore


class InternalServerError(GraphQLError):
    """内部服务器错误."""

    def __init__(self) -> None:
        """初始化内部服务器错误."""
        super().__init__("Internal server error")


class GraphQLInvalidActionError(GraphQLError):
    """无效的操作类型."""

    def __init__(self, action: str) -> None:
        """初始化无效操作错误."""
        super().__init__(f"Invalid action: {action!r}")


class GraphQLEventNotFoundError(GraphQLError):
    """事件不存在."""

    def __init__(self, event_id: str) -> None:
        """初始化事件不存在错误."""
        super().__init__(f"Event not found: {event_id!r}")


logger = logging.getLogger(__name__)


def _preset_store() -> TOMLStore:
    return TOMLStore(DATA_DIR, Path("scenario_presets.toml"), list)


def _input_to_context_dict(input_obj: DrivingContextInput) -> dict[str, Any]:
    result: dict[str, Any] = {
        "scenario": input_obj.scenario.value
        if hasattr(input_obj.scenario, "value")
        else input_obj.scenario,
        "driver": {},
        "spatial": {},
        "traffic": {},
    }
    if input_obj.driver:
        driver = input_obj.driver
        result["driver"] = {
            "emotion": driver.emotion.value
            if hasattr(driver.emotion, "value")
            else driver.emotion,
            "workload": driver.workload.value
            if hasattr(driver.workload, "value")
            else driver.workload,
            "fatigue_level": driver.fatigue_level,
        }
    if input_obj.spatial:
        spatial: dict[str, Any] = {"current_location": {}}
        if input_obj.spatial.current_location:
            spatial["current_location"] = {
                "latitude": input_obj.spatial.current_location.latitude,
                "longitude": input_obj.spatial.current_location.longitude,
                "address": input_obj.spatial.current_location.address,
                "speed_kmh": input_obj.spatial.current_location.speed_kmh,
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
        traffic = input_obj.traffic
        result["traffic"] = {
            "congestion_level": traffic.congestion_level.value
            if hasattr(traffic.congestion_level, "value")
            else traffic.congestion_level,
            "incidents": traffic.incidents,
            "estimated_delay_minutes": traffic.estimated_delay_minutes,
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
    async def process_query(
        self,
        query_input: Annotated[ProcessQueryInput, strawberry.argument(name="input")],
    ) -> ProcessQueryResult:
        """处理用户查询并返回工作流结果."""
        try:
            mm = get_memory_module()
            workflow = AgentWorkflow(
                data_dir=DATA_DIR,
                memory_mode=MemoryMode(query_input.memory_mode.value),
                memory_module=mm,
            )

            driving_context = None
            if query_input.context:
                ctx_dict = _input_to_context_dict(query_input.context)
                driving_context = DrivingContext(**ctx_dict).model_dump()

            result, event_id, stages = await workflow.run_with_stages(
                query_input.query,
                driving_context,
            )
            return ProcessQueryResult(
                result=result,
                event_id=event_id,
                stages=WorkflowStagesGQL(
                    context=cast("Any", stages.context),
                    task=cast("Any", stages.task),
                    decision=cast("Any", stages.decision),
                    execution=cast("Any", stages.execution),
                ),
            )
        except GraphQLError:
            raise
        except Exception as e:
            logger.exception("processQuery failed")
            raise InternalServerError from e

    @strawberry.mutation
    async def submit_feedback(
        self,
        feedback_input: Annotated[FeedbackInput, strawberry.argument(name="input")],
    ) -> FeedbackResult:
        """提交用户反馈."""
        if feedback_input.action not in ("accept", "ignore"):
            raise GraphQLInvalidActionError(feedback_input.action)
        try:
            mm = get_memory_module()
            safe_action: Literal["accept", "ignore"]
            safe_action = "accept" if feedback_input.action == "accept" else "ignore"
            mode = MemoryMode(feedback_input.memory_mode.value)
            actual_type = await mm.get_event_type(
                feedback_input.event_id,
                mode=mode,
                user_id="default",
            )
        except Exception as e:
            logger.exception("submitFeedback failed")
            raise InternalServerError from e

        if actual_type is None:
            raise GraphQLEventNotFoundError(feedback_input.event_id)

        try:
            feedback = FeedbackData(
                action=safe_action,
                type=actual_type,
                modified_content=feedback_input.modified_content,
            )
            await mm.update_feedback(
                feedback_input.event_id, feedback, mode=mode, user_id="default"
            )
        except GraphQLError:
            raise
        except Exception as e:
            logger.exception("submitFeedback failed")
            raise InternalServerError from e

        return FeedbackResult(status="success")

    @strawberry.mutation
    async def save_scenario_preset(
        self,
        preset_input: Annotated[ScenarioPresetInput, strawberry.argument(name="input")],
    ) -> ScenarioPresetGQL:
        """保存场景预设."""
        store = _preset_store()
        preset = ScenarioPreset(name=preset_input.name)
        if preset_input.context:
            preset.context = DrivingContext(
                **_input_to_context_dict(preset_input.context)
            )
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
