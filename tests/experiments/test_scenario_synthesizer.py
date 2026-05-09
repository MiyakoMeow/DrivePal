"""测试场景合成器（不调用真实 LLM）."""

import json
from typing import TYPE_CHECKING

from experiments.ablation.scenario_synthesizer import (
    load_scenarios,
    sample_scenarios,
)
from experiments.ablation.types import Scenario

if TYPE_CHECKING:
    from pathlib import Path


def test_load_scenarios_empty(tmp_path: Path):
    path = tmp_path / "empty.jsonl"
    path.touch()
    scenarios = load_scenarios(path)
    assert scenarios == []


def test_load_scenarios(tmp_path: Path):
    data = {
        "id": "test-1",
        "driving_context": {},
        "user_query": "测试",
        "expected_decision": {},
        "expected_task_type": "meeting",
        "safety_relevant": False,
        "scenario_type": "city",
    }
    path = tmp_path / "scenarios.jsonl"
    path.write_text(json.dumps(data) + "\n")
    scenarios = load_scenarios(path)
    assert len(scenarios) == 1
    assert scenarios[0].id == "test-1"


def test_sample_scenarios_safety_only():
    scenarios = [
        Scenario("s1", {}, "", {}, "", safety_relevant=True, scenario_type=""),
        Scenario("s2", {}, "", {}, "", safety_relevant=False, scenario_type=""),
        Scenario("s3", {}, "", {}, "", safety_relevant=True, scenario_type=""),
    ]
    sampled = sample_scenarios(scenarios, 2, safety_only=True, seed=42)
    assert len(sampled) == 2
    assert all(s.safety_relevant for s in sampled)


def test_sample_scenarios_all():
    scenarios = [
        Scenario("s1", {}, "", {}, "", safety_relevant=True, scenario_type=""),
        Scenario("s2", {}, "", {}, "", safety_relevant=False, scenario_type=""),
    ]
    sampled = sample_scenarios(scenarios, 2, safety_only=False)
    assert len(sampled) == 2
