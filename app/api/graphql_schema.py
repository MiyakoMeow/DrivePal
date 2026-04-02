"""Strawberry GraphQL Schema 定义."""

from __future__ import annotations

from enum import Enum
from typing import Optional

import strawberry
from strawberry.scalars import JSON


@strawberry.enum
class MemoryModeEnum(Enum):
    """记忆模式枚举."""

    MEMORY_BANK = "memory_bank"
    MEMOCHAT = "memochat"


@strawberry.enum
class EmotionEnum(Enum):
    """驾驶员情绪枚举."""

    NEUTRAL = "neutral"
    ANXIOUS = "anxious"
    FATIGUED = "fatigued"
    CALM = "calm"
    ANGRY = "angry"


@strawberry.enum
class WorkloadEnum(Enum):
    """工作负荷枚举."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    OVERLOADED = "overloaded"


@strawberry.enum
class CongestionLevelEnum(Enum):
    """拥堵等级枚举."""

    SMOOTH = "smooth"
    SLOW = "slow"
    CONGESTED = "congested"
    BLOCKED = "blocked"


@strawberry.enum
class ScenarioEnum(Enum):
    """驾驶场景枚举."""

    PARKED = "parked"
    CITY_DRIVING = "city_driving"
    HIGHWAY = "highway"
    TRAFFIC_JAM = "traffic_jam"


@strawberry.input
class GeoLocationInput:
    """地理位置输入."""

    latitude: float
    longitude: float
    address: str = ""
    speed_kmh: float = 0.0


@strawberry.input
class DriverStateInput:
    """驾驶员状态输入."""

    emotion: EmotionEnum = EmotionEnum.NEUTRAL
    workload: WorkloadEnum = WorkloadEnum.NORMAL
    fatigue_level: float = 0.0


@strawberry.input
class SpatioTemporalContextInput:
    """时空上下文输入."""

    current_location: Optional[GeoLocationInput] = None
    destination: Optional[GeoLocationInput] = None
    eta_minutes: Optional[float] = None
    heading: Optional[float] = None


@strawberry.input
class TrafficConditionInput:
    """交通状况输入."""

    congestion_level: CongestionLevelEnum = CongestionLevelEnum.SMOOTH
    incidents: list[str] = strawberry.field(default_factory=list)
    estimated_delay_minutes: int = 0


@strawberry.input
class DrivingContextInput:
    """驾驶上下文输入."""

    driver: Optional[DriverStateInput] = None
    spatial: Optional[SpatioTemporalContextInput] = None
    traffic: Optional[TrafficConditionInput] = None
    scenario: ScenarioEnum = ScenarioEnum.PARKED


@strawberry.input
class ProcessQueryInput:
    """处理查询输入."""

    query: str
    memory_mode: MemoryModeEnum = MemoryModeEnum.MEMORY_BANK
    context: Optional[DrivingContextInput] = None


@strawberry.input
class FeedbackInput:
    """反馈输入."""

    event_id: str
    action: str
    modified_content: Optional[str] = None


@strawberry.input
class ScenarioPresetInput:
    """场景预设输入."""

    name: str
    context: DrivingContextInput


JSONScalar = strawberry.scalar(
    name="JSON",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)


@strawberry.type
class GeoLocationGQL:
    """地理位置输出."""

    latitude: float
    longitude: float
    address: str
    speed_kmh: float


@strawberry.type
class DriverStateGQL:
    """驾驶员状态输出."""

    emotion: str
    workload: str
    fatigue_level: float


@strawberry.type
class SpatioTemporalContextGQL:
    """时空上下文输出."""

    current_location: Optional[GeoLocationGQL]
    destination: Optional[GeoLocationGQL]
    eta_minutes: Optional[float]
    heading: Optional[float]


@strawberry.type
class TrafficConditionGQL:
    """交通状况输出."""

    congestion_level: str
    incidents: list[str]
    estimated_delay_minutes: int


@strawberry.type
class DrivingContextGQL:
    """驾驶上下文输出."""

    driver: DriverStateGQL
    spatial: SpatioTemporalContextGQL
    traffic: TrafficConditionGQL
    scenario: str


@strawberry.type
class WorkflowStagesGQL:
    """工作流各阶段输出."""

    context: JSON
    task: JSON
    decision: JSON
    execution: JSON


@strawberry.type
class ProcessQueryResult:
    """处理查询结果."""

    result: str
    event_id: Optional[str]
    stages: Optional[WorkflowStagesGQL]


@strawberry.type
class MemoryEventGQL:
    """记忆事件."""

    id: str
    content: str
    type: str
    description: str
    created_at: str


@strawberry.type
class ExperimentReport:
    """实验报告."""

    report: str


@strawberry.type
class ScenarioPresetGQL:
    """场景预设."""

    id: str
    name: str
    context: DrivingContextGQL
    created_at: str


@strawberry.type
class FeedbackResult:
    """反馈结果."""

    status: str
