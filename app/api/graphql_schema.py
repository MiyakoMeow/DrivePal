"""Strawberry GraphQL Schema 定义."""

from __future__ import annotations

from enum import Enum
from typing import Optional

import strawberry


@strawberry.enum
class MemoryModeEnum(Enum):
    MEMORY_BANK = "memory_bank"
    MEMOCHAT = "memochat"


@strawberry.input
class GeoLocationInput:
    latitude: float
    longitude: float
    address: str = ""
    speed_kmh: float = 0.0


@strawberry.input
class DriverStateInput:
    emotion: str = "neutral"
    workload: str = "normal"
    fatigue_level: float = 0.0


@strawberry.input
class SpatioTemporalContextInput:
    current_location: GeoLocationInput
    destination: Optional[GeoLocationInput] = None
    eta_minutes: Optional[float] = None
    heading: Optional[float] = None


@strawberry.input
class TrafficConditionInput:
    congestion_level: str = "smooth"
    incidents: list[str] = strawberry.field(default_factory=list)
    estimated_delay_minutes: int = 0


@strawberry.input
class DrivingContextInput:
    driver: Optional[DriverStateInput] = None
    spatial: Optional[SpatioTemporalContextInput] = None
    traffic: Optional[TrafficConditionInput] = None
    scenario: str = "parked"


@strawberry.input
class ProcessQueryInput:
    query: str
    memory_mode: MemoryModeEnum = MemoryModeEnum.MEMORY_BANK
    context: Optional[DrivingContextInput] = None


@strawberry.input
class FeedbackInput:
    event_id: str
    action: str
    modified_content: Optional[str] = None


@strawberry.input
class ScenarioPresetInput:
    name: str
    context: DrivingContextInput


class _JSON:
    pass


JSON = strawberry.scalar(
    _JSON,
    serialize=lambda v: v,
    parse_value=lambda v: v,
)


@strawberry.type
class GeoLocationGQL:
    latitude: float
    longitude: float
    address: str
    speed_kmh: float


@strawberry.type
class DriverStateGQL:
    emotion: str
    workload: str
    fatigue_level: float


@strawberry.type
class SpatioTemporalContextGQL:
    current_location: GeoLocationGQL
    destination: Optional[GeoLocationGQL]
    eta_minutes: Optional[float]
    heading: Optional[float]


@strawberry.type
class TrafficConditionGQL:
    congestion_level: str
    incidents: list[str]
    estimated_delay_minutes: int


@strawberry.type
class DrivingContextGQL:
    driver: DriverStateGQL
    spatial: SpatioTemporalContextGQL
    traffic: TrafficConditionGQL
    scenario: str


@strawberry.type
class WorkflowStagesGQL:
    context: JSON
    task: JSON
    decision: JSON
    execution: JSON


@strawberry.type
class ProcessQueryResult:
    result: str
    event_id: Optional[str]
    stages: Optional[WorkflowStagesGQL]


@strawberry.type
class MemoryEventGQL:
    id: str
    content: str
    type: str
    description: str
    created_at: str


@strawberry.type
class ExperimentReport:
    report: str


@strawberry.type
class ScenarioPresetGQL:
    id: str
    name: str
    context: DrivingContextGQL
    created_at: str


@strawberry.type
class FeedbackResult:
    status: str
