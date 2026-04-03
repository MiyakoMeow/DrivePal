"""Mutation resolvers."""

from __future__ import annotations

import logging
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
    ProcessQueryInput,
    ProcessQueryResult,
    SpatioTemporalContextGQL,
    TrafficConditionGQL,
    WorkflowStagesGQL,
)
from app.memory.schemas import FeedbackData
from app.memory.types import MemoryMode
from app.schemas.context import DrivingContext

logger = logging.getLogger(__name__)


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
                ctx_dict = _input_to_context_dict(input.context)
                driving_context = DrivingContext(**ctx_dict).model_dump()

            result, event_id, stages = await workflow.run_with_stages(
                input.query, driving_context
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
