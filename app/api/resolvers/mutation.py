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
    DriverState,
    DrivingContext,
    GeoLocation,
    ScenarioPreset,
    SpatioTemporalContext,
    TrafficCondition,
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


def _input_to_context(input_obj: DrivingContextInput) -> DrivingContext:
    """Convert Strawberry GraphQL input to Pydantic DrivingContext."""
    driver = None
    if input_obj.driver:
        driver = DriverState(
            emotion=input_obj.driver.emotion.value,
            workload=input_obj.driver.workload.value,
            fatigue_level=input_obj.driver.fatigue_level,
        )
    spatial = None
    if input_obj.spatial:
        cl: GeoLocation | None = None
        if input_obj.spatial.current_location:
            cl = GeoLocation(
                latitude=input_obj.spatial.current_location.latitude,
                longitude=input_obj.spatial.current_location.longitude,
                address=input_obj.spatial.current_location.address,
                speed_kmh=input_obj.spatial.current_location.speed_kmh,
            )
        dest: GeoLocation | None = None
        if input_obj.spatial.destination:
            dest = GeoLocation(
                latitude=input_obj.spatial.destination.latitude,
                longitude=input_obj.spatial.destination.longitude,
                address=input_obj.spatial.destination.address,
                speed_kmh=input_obj.spatial.destination.speed_kmh,
            )
        spatial = SpatioTemporalContext(
            current_location=cl or GeoLocation(),
            destination=dest,
            eta_minutes=input_obj.spatial.eta_minutes,
            heading=input_obj.spatial.heading,
        )
    traffic = None
    if input_obj.traffic:
        traffic = TrafficCondition(
            congestion_level=input_obj.traffic.congestion_level.value,
            incidents=input_obj.traffic.incidents,
            estimated_delay_minutes=input_obj.traffic.estimated_delay_minutes,
        )
    return DrivingContext(
        driver=driver or DriverState(),
        spatial=spatial or SpatioTemporalContext(),
        traffic=traffic or TrafficCondition(),
        scenario=input_obj.scenario.value,
    )


def _dict_to_gql_context(d: dict[str, Any]) -> DrivingContextGQL:
    """Convert dict to DrivingContextGQL via Pydantic validation."""
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
                driving_context = _input_to_context(query_input.context).model_dump()

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
            )
        except OSError as e:
            msg = f"Storage error: {e}"
            raise GraphQLError(msg) from e
        except RuntimeError as e:
            msg = f"Runtime error: {e}"
            raise GraphQLError(msg) from e
        except ValueError as e:
            msg = f"Validation error: {e}"
            raise GraphQLError(msg) from e
        except Exception as e:
            logger.exception("submitFeedback failed (get_event_type)")
            raise InternalServerError from e

        if actual_type is None:
            raise GraphQLEventNotFoundError(feedback_input.event_id)

        try:
            feedback = FeedbackData(
                action=safe_action,
                type=actual_type,
                modified_content=feedback_input.modified_content,
            )
            await mm.update_feedback(feedback_input.event_id, feedback, mode=mode)
        except GraphQLError:
            raise
        except OSError as e:
            msg = f"Storage error: {e}"
            raise GraphQLError(msg) from e
        except RuntimeError as e:
            msg = f"Runtime error: {e}"
            raise GraphQLError(msg) from e
        except ValueError as e:
            msg = f"Validation error: {e}"
            raise GraphQLError(msg) from e
        except Exception as e:
            logger.exception("submitFeedback failed (update_feedback)")
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
            preset.context = _input_to_context(preset_input.context)
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
