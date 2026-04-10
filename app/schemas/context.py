"""驾驶上下文数据模型定义."""

import uuid
from datetime import datetime, UTC
from typing import Literal

from pydantic import BaseModel, Field


class DriverState(BaseModel):
    """驾驶员状态模型."""

    emotion: Literal["neutral", "anxious", "fatigued", "calm", "angry"] = "neutral"
    workload: Literal["low", "normal", "high", "overloaded"] = "normal"
    fatigue_level: float = Field(default=0.0, ge=0.0, le=1.0)


class GeoLocation(BaseModel):
    """地理位置模型."""

    latitude: float = Field(default=0.0, ge=-90.0, le=90.0)
    longitude: float = Field(default=0.0, ge=-180.0, le=180.0)
    address: str = ""
    speed_kmh: float = Field(default=0.0, ge=0.0)


class SpatioTemporalContext(BaseModel):
    """时空上下文模型."""

    current_location: GeoLocation = Field(default_factory=GeoLocation)
    destination: GeoLocation | None = None
    eta_minutes: float | None = Field(default=None, ge=0)
    heading: float | None = Field(default=None, ge=0, le=360)


class TrafficCondition(BaseModel):
    """交通状况模型."""

    congestion_level: Literal["smooth", "slow", "congested", "blocked"] = "smooth"
    incidents: list[str] = Field(default_factory=list)
    estimated_delay_minutes: int = Field(default=0, ge=0)


class DrivingContext(BaseModel):
    """驾驶上下文聚合模型."""

    driver: DriverState = Field(default_factory=DriverState)
    spatial: SpatioTemporalContext = Field(default_factory=SpatioTemporalContext)
    traffic: TrafficCondition = Field(default_factory=TrafficCondition)
    scenario: Literal["parked", "city_driving", "highway", "traffic_jam"] = "parked"


class ScenarioPreset(BaseModel):
    """场景预设模型."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    context: DrivingContext = Field(default_factory=DrivingContext)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
