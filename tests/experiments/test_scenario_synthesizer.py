"""测试场景合成器（不调用真实 LLM）."""

import json
import tempfile
from pathlib import Path

from experiments.ablation.scenario_synthesizer import (
    load_scenarios,
    sample_scenarios,
)
from experiments.ablation.types import Scenario


def test_load_scenarios_empty():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        pass
    path = Path(f.name)
    scenarios = load_scenarios(path)
    assert scenarios == []
    path.unlink()


def test_load_scenarios():
    data = {
        "id": "test-1",
        "driving_context": {},
        "user_query": "测试",
        "expected_decision": {},
        "expected_task_type": "meeting",
        "safety_relevant": False,
        "scenario_type": "city",
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(json.dumps(data) + "\n")
    path = Path(f.name)
    scenarios = load_scenarios(path)
    assert len(scenarios) == 1
    assert scenarios[0].id == "test-1"
    path.unlink()


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
