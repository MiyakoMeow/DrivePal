"""Strawberry GraphQL Schema 定义."""

from enum import Enum

import strawberry
from strawberry import auto
from strawberry.experimental.pydantic import type as pydantic_type
from strawberry.scalars import JSON

from app.schemas.context import (
    DriverState as _DriverState,
)
from app.schemas.context import (
    DrivingContext as _DrivingContext,
)
from app.schemas.context import (
    GeoLocation as _GeoLocation,
)
from app.schemas.context import (
    SpatioTemporalContext as _SpatioTemporalContext,
)
from app.schemas.context import (
    TrafficCondition as _TrafficCondition,
)


@strawberry.enum
class MemoryModeEnum(Enum):
    """记忆模式枚举."""

    MEMORY_BANK = "memory_bank"


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

    current_location: GeoLocationInput | None = None
    destination: GeoLocationInput | None = None
    eta_minutes: float | None = None
    heading: float | None = None


@strawberry.input
class TrafficConditionInput:
    """交通状况输入."""

    congestion_level: CongestionLevelEnum = CongestionLevelEnum.SMOOTH
    incidents: list[str] = strawberry.field(default_factory=list)
    estimated_delay_minutes: int = 0


@strawberry.input
class DrivingContextInput:
    """驾驶上下文输入."""

    driver: DriverStateInput | None = None
    spatial: SpatioTemporalContextInput | None = None
    traffic: TrafficConditionInput | None = None
    scenario: ScenarioEnum = ScenarioEnum.PARKED
    passengers: list[str] = strawberry.field(default_factory=list)


@strawberry.input
class ProcessQueryInput:
    """处理查询输入."""

    query: str
    memory_mode: MemoryModeEnum = MemoryModeEnum.MEMORY_BANK
    context: DrivingContextInput | None = None
    current_user: str = "default"


@strawberry.input
class FeedbackInput:
    """反馈输入."""

    event_id: str
    action: str
    memory_mode: MemoryModeEnum = MemoryModeEnum.MEMORY_BANK
    modified_content: str | None = None
    current_user: str = "default"


@strawberry.input
class ScenarioPresetInput:
    """场景预设输入."""

    name: str
    context: DrivingContextInput
    current_user: str = "default"


JSONScalar = strawberry.scalar(
    name="JSON",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)


@pydantic_type(_GeoLocation)
class GeoLocationGQL:
    """地理位置输出."""

    latitude: auto
    longitude: auto
    address: auto
    speed_kmh: auto


@pydantic_type(_DriverState)
class DriverStateGQL:
    """驾驶员状态输出."""

    emotion: str
    workload: str
    fatigue_level: auto


@pydantic_type(_TrafficCondition)
class TrafficConditionGQL:
    """交通状况输出."""

    congestion_level: str
    incidents: auto
    estimated_delay_minutes: auto


@pydantic_type(_SpatioTemporalContext)
class SpatioTemporalContextGQL:
    """时空上下文输出."""

    current_location: auto
    destination: auto
    eta_minutes: auto
    heading: auto


@pydantic_type(_DrivingContext)
class DrivingContextGQL:
    """驾驶上下文输出."""

    driver: auto
    spatial: auto
    traffic: auto
    scenario: str
    passengers: auto


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
    event_id: str | None
    stages: WorkflowStagesGQL | None


@strawberry.type
class MemoryEventGQL:
    """记忆事件."""

    id: str
    content: str
    type: str
    description: str
    created_at: str


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


@strawberry.type
class ExportDataResult:
    """导出数据结果."""

    files: JSON


@strawberry.type
class ExperimentResult:
    """单策略实验结果."""

    strategy: str
    exact_match: float
    field_f1: float
    value_f1: float


@strawberry.type
class ExperimentResults:
    """五策略对比实验结果."""

    strategies: list[ExperimentResult]
