"""上下文数据模型测试."""

import pytest
from pydantic import ValidationError

from app.schemas.context import (
    DriverState,
    GeoLocation,
    SpatioTemporalContext,
    TrafficCondition,
    DrivingContext,
    ScenarioPreset,
)


def test_driver_state_defaults() -> None:
    ds = DriverState()
    assert ds.emotion == "neutral"
    assert ds.workload == "normal"
    assert ds.fatigue_level == 0.0


def test_driver_state_invalid_emotion() -> None:
    with pytest.raises(ValidationError):
        DriverState.model_validate({"emotion": "happy"})


def test_driver_state_invalid_workload() -> None:
    with pytest.raises(ValidationError):
        DriverState.model_validate({"workload": "extreme"})


def test_driver_state_fatigue_bounds() -> None:
    DriverState(fatigue_level=0.0)
    DriverState(fatigue_level=1.0)
    with pytest.raises(ValidationError):
        DriverState.model_validate({"fatigue_level": 1.5})
    with pytest.raises(ValidationError):
        DriverState.model_validate({"fatigue_level": -0.1})


def test_geo_location_bounds() -> None:
    GeoLocation(latitude=90.0, longitude=180.0)
    with pytest.raises(ValidationError):
        GeoLocation.model_validate({"latitude": 91.0})
    with pytest.raises(ValidationError):
        GeoLocation.model_validate({"longitude": -181.0})


def test_spatio_temporal_context_defaults() -> None:
    st = SpatioTemporalContext()
    assert st.current_location == GeoLocation()
    assert st.destination is None
    assert st.eta_minutes is None


def test_traffic_condition_defaults() -> None:
    tc = TrafficCondition()
    assert tc.congestion_level == "smooth"
    assert tc.incidents == []
    assert tc.estimated_delay_minutes == 0


def test_traffic_condition_invalid_congestion() -> None:
    with pytest.raises(ValidationError):
        TrafficCondition.model_validate({"congestion_level": "unknown"})


def test_driving_context_defaults() -> None:
    dc = DrivingContext()
    assert dc.scenario == "parked"
    assert dc.driver == DriverState()


def test_driving_context_to_dict() -> None:
    dc = DrivingContext(
        driver=DriverState(emotion="calm", fatigue_level=0.3),
        scenario="highway",
    )
    d = dc.model_dump()
    assert d["driver"]["emotion"] == "calm"
    assert d["scenario"] == "highway"


def test_scenario_preset_auto_id_and_timestamp() -> None:
    sp = ScenarioPreset(name="test")
    assert sp.id != ""
    assert len(sp.id) == 12
    assert sp.created_at != ""


def test_scenario_preset_round_trip() -> None:
    sp = ScenarioPreset(name="parked", context=DrivingContext(scenario="parked"))
    d = sp.model_dump()
    sp2 = ScenarioPreset(**d)
    assert sp2.name == "parked"
    assert sp2.context.scenario == "parked"
