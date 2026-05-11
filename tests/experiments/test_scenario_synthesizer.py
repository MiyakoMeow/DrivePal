"""测试场景合成器（不调用真实 LLM）."""

import json
from typing import TYPE_CHECKING

import pytest

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


def test_sample_scenarios_stratified():
    """分层抽样应保证每层至少 min_per_stratum 个样本。"""
    scenarios = [
        Scenario(f"s{i}", {"type": "a" if i < 3 else "b"}, "", {}, "", safety_relevant=False, scenario_type="")
        for i in range(6)
    ]
    sampled = sample_scenarios(
        scenarios,
        4,
        stratify_key=lambda s: s.driving_context.get("type", "unknown"),
        min_per_stratum=1,
        seed=42,
    )
    assert len(sampled) == 4
    types = {s.driving_context.get("type") for s in sampled}
    assert "a" in types
    assert "b" in types


def test_sample_scenarios_exclude_ids():
    """exclude_ids 应排除指定场景。"""
    scenarios = [
        Scenario("s1", {}, "", {}, "", safety_relevant=False, scenario_type=""),
        Scenario("s2", {}, "", {}, "", safety_relevant=False, scenario_type=""),
        Scenario("s3", {}, "", {}, "", safety_relevant=False, scenario_type=""),
    ]
    sampled = sample_scenarios(scenarios, 2, exclude_ids={"s1"}, seed=42)
    assert len(sampled) == 2
    assert all(s.id != "s1" for s in sampled)


def test_sample_scenarios_empty_pool_raises():
    """排除后池为空应抛出 ValueError。"""
    scenarios = [
        Scenario("s1", {}, "", {}, "", safety_relevant=False, scenario_type=""),
    ]
    with pytest.raises(ValueError, match="无可用的场景"):
        sample_scenarios(scenarios, 1, exclude_ids={"s1"})


def test_sample_scenarios_min_per_stratum_too_large():
    """min_per_stratum 总和超过 n 时应抛出 ValueError。"""
    scenarios = [
        Scenario(f"s{i}", {"type": f"t{i}"}, "", {}, "", safety_relevant=False, scenario_type="")
        for i in range(5)
    ]
    with pytest.raises(ValueError, match="无法满足 min_per_stratum"):
        sample_scenarios(
            scenarios,
            3,
            stratify_key=lambda s: s.driving_context.get("type", "unknown"),
            min_per_stratum=1,
            seed=42,
        )
