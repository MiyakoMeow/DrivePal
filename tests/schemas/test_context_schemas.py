"""上下文数据模型测试."""

import pytest
from pydantic import ValidationError

from app.schemas.context import (
    DriverState,
    DrivingContext,
    GeoLocation,
    ScenarioPreset,
    SpatioTemporalContext,
    TrafficCondition,
)

# PLR2004: ScenarioPreset ID 长度
EXPECTED_SCENARIO_ID_LENGTH = 12


def test_driver_state_defaults() -> None:
    """验证 DriverState 的默认值."""
    ds = DriverState()
    assert ds.emotion == "neutral"
    assert ds.workload == "normal"
    assert ds.fatigue_level == 0.0


def test_driver_state_invalid_emotion() -> None:
    """验证无效 emotion 值被拒绝."""
    with pytest.raises(ValidationError):
        DriverState.model_validate({"emotion": "happy"})


def test_driver_state_invalid_workload() -> None:
    """验证无效 workload 值被拒绝."""
    with pytest.raises(ValidationError):
        DriverState.model_validate({"workload": "extreme"})


def test_driver_state_fatigue_bounds() -> None:
    """验证 fatigue_level 在 [0, 1] 范围内."""
    DriverState(fatigue_level=0.0)
    DriverState(fatigue_level=1.0)
    with pytest.raises(ValidationError):
        DriverState.model_validate({"fatigue_level": 1.5})
    with pytest.raises(ValidationError):
        DriverState.model_validate({"fatigue_level": -0.1})


def test_geo_location_bounds() -> None:
    """验证 GeoLocation 经纬度边界验证."""
    GeoLocation(latitude=90.0, longitude=180.0)
    with pytest.raises(ValidationError):
        GeoLocation.model_validate({"latitude": 91.0})
    with pytest.raises(ValidationError):
        GeoLocation.model_validate({"longitude": -181.0})


def test_spatio_temporal_context_defaults() -> None:
    """验证 SpatioTemporalContext 的默认值."""
    st = SpatioTemporalContext()
    assert st.current_location == GeoLocation()
    assert st.destination is None
    assert st.eta_minutes is None


def test_traffic_condition_defaults() -> None:
    """验证 TrafficCondition 的默认值."""
    tc = TrafficCondition()
    assert tc.congestion_level == "smooth"
    assert tc.incidents == []
    assert tc.estimated_delay_minutes == 0


def test_traffic_condition_invalid_congestion() -> None:
    """验证无效 congestion_level 值被拒绝."""
    with pytest.raises(ValidationError):
        TrafficCondition.model_validate({"congestion_level": "unknown"})


def test_driving_context_defaults() -> None:
    """验证 DrivingContext 的默认值."""
    dc = DrivingContext()
    assert dc.scenario == "parked"
    assert dc.driver == DriverState()


def test_driving_context_to_dict() -> None:
    """验证 DrivingContext 序列化为字典."""
    dc = DrivingContext(
        driver=DriverState(emotion="calm", fatigue_level=0.3),
        scenario="highway",
    )
    d = dc.model_dump()
    assert d["driver"]["emotion"] == "calm"
    assert d["scenario"] == "highway"


def test_scenario_preset_auto_id_and_timestamp() -> None:
    """验证 ScenarioPreset 自动生成 id 和 created_at."""
    sp = ScenarioPreset(name="test")
    assert sp.id != ""
    assert len(sp.id) == EXPECTED_SCENARIO_ID_LENGTH
    assert sp.created_at != ""


def test_scenario_preset_round_trip() -> None:
    """验证 ScenarioPreset 序列化和反序列化."""
    sp = ScenarioPreset(name="parked", context=DrivingContext(scenario="parked"))
    d = sp.model_dump()
    sp2 = ScenarioPreset(**d)
    assert sp2.name == "parked"
    assert sp2.context.scenario == "parked"


def test_process_query_request_validates_context() -> None:
    """ProcessQueryRequest.context 接受 DrivingContext 结构."""
    from app.schemas.query import ProcessQueryRequest

    req = ProcessQueryRequest(
        query="测试",
        context={
            "driver": {"emotion": "calm"},
            "scenario": "highway",
        },
    )
    assert req.context is not None
    assert req.context.scenario == "highway"


def test_process_query_request_invalid_context_raises() -> None:
    """ProcessQueryRequest.context 拒绝非法字段值."""
    from app.schemas.query import ProcessQueryRequest

    with pytest.raises(ValidationError):
        ProcessQueryRequest(
            query="测试",
            context={"scenario": "invalid_scenario"},
        )
