from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.schemas.context import DrivingContext
from app.simulation.state import reset_state, simulation_state


def test_singleton_returns_same_instance() -> None:
    from app.simulation.state import simulation_state as state2

    assert state2 is simulation_state


def test_get_context_returns_driving_context() -> None:
    ctx = simulation_state.get_context()
    assert isinstance(ctx, DrivingContext)


def test_get_context_returns_defaults() -> None:
    ctx = simulation_state.get_context()
    assert ctx.scenario == "parked"
    assert ctx.driver.emotion == "neutral"
    assert ctx.spatial.current_location.speed_kmh == 0.0


def test_update_top_level_field() -> None:
    simulation_state.update("scenario", "highway")
    assert simulation_state.get_context().scenario == "highway"
    reset_state()


def test_update_nested_field_one_level() -> None:
    simulation_state.update("driver.emotion", "anxious")
    assert simulation_state.get_context().driver.emotion == "anxious"
    reset_state()


def test_update_deeply_nested_field() -> None:
    simulation_state.update("spatial.current_location.speed_kmh", 80.0)
    assert simulation_state.get_context().spatial.current_location.speed_kmh == 80.0
    reset_state()


def test_update_invalid_field_path_raises() -> None:
    with pytest.raises((KeyError, AttributeError, ValueError)):
        simulation_state.update("nonexistent.field", 1)


def test_update_invalid_value_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        simulation_state.update("scenario", "flying")


def test_update_invalid_nested_value_raises() -> None:
    with pytest.raises(ValidationError):
        simulation_state.update("driver.fatigue_level", 1.5)


def test_set_preset() -> None:
    preset = {
        "scenario": "traffic_jam",
        "driver": {"emotion": "angry", "workload": "high", "fatigue_level": 0.8},
    }
    simulation_state.set_preset(preset)
    ctx = simulation_state.get_context()
    assert ctx.scenario == "traffic_jam"
    assert ctx.driver.emotion == "angry"
    assert ctx.driver.fatigue_level == 0.8
    assert ctx.driver.workload == "high"
    reset_state()


def test_set_preset_validates() -> None:
    with pytest.raises(ValidationError):
        simulation_state.set_preset({"scenario": "invalid_value"})


def test_reset_returns_defaults() -> None:
    simulation_state.update("scenario", "highway")
    simulation_state.update("driver.emotion", "fatigued")
    reset_state()
    ctx = simulation_state.get_context()
    assert ctx.scenario == "parked"
    assert ctx.driver.emotion == "neutral"


def test_reset_isolated_from_context_reference() -> None:
    ctx = simulation_state.get_context()
    ctx.scenario = "highway"
    assert simulation_state.get_context().scenario == "highway"
    reset_state()
    assert simulation_state.get_context().scenario == "parked"


def test_update_does_not_affect_previous_references() -> None:
    before = deepcopy(simulation_state.get_context())
    simulation_state.update("scenario", "city_driving")
    assert before.scenario == "parked"
    assert simulation_state.get_context().scenario == "city_driving"
    reset_state()
