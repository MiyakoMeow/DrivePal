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


def _sc(
    sid: str,
    driving_context: dict | None = None,
    *,
    safety_relevant: bool = False,
    synthesis_dims: dict | None = None,
) -> Scenario:
    """快速构造测试 Scenario，减少重复参数。"""
    return Scenario(
        id=sid,
        driving_context=driving_context or {},
        user_query="",
        expected_decision={},
        expected_task_type="",
        safety_relevant=safety_relevant,
        scenario_type="",
        synthesis_dims=synthesis_dims or {},
    )


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
        _sc("s1", safety_relevant=True),
        _sc("s2", safety_relevant=False),
        _sc("s3", safety_relevant=True),
    ]
    sampled = sample_scenarios(scenarios, 2, safety_only=True, seed=42)
    assert len(sampled) == 2
    assert all(s.safety_relevant for s in sampled)


def test_sample_scenarios_all():
    scenarios = [
        _sc("s1", safety_relevant=True),
        _sc("s2", safety_relevant=False),
    ]
    sampled = sample_scenarios(scenarios, 2, safety_only=False)
    assert len(sampled) == 2


def test_sample_scenarios_stratified():
    """分层抽样应保证每层至少 min_per_stratum 个样本。"""
    scenarios = [_sc(f"s{i}", {"type": "a" if i < 3 else "b"}) for i in range(6)]
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
        _sc("s1"),
        _sc("s2"),
        _sc("s3"),
    ]
    sampled = sample_scenarios(scenarios, 2, exclude_ids={"s1"}, seed=42)
    assert len(sampled) == 2
    assert all(s.id != "s1" for s in sampled)


def test_sample_scenarios_empty_pool_raises():
    """排除后池为空应抛出 ValueError。"""
    scenarios = [_sc("s1")]
    with pytest.raises(ValueError, match="无可用的场景"):
        sample_scenarios(scenarios, 1, exclude_ids={"s1"})


def test_sample_scenarios_min_per_stratum_too_large_falls_back():
    """min_per_stratum 总和超过 n 时回退简单随机抽样，不抛异常。"""
    scenarios = [_sc(f"s{i}", {"type": f"t{i}"}) for i in range(5)]
    result = sample_scenarios(
        scenarios,
        3,
        stratify_key=lambda s: s.driving_context.get("type", "unknown"),
        min_per_stratum=1,
        seed=42,
    )
    assert len(result) == 3


def test_safety_stratum_combined_keys():
    """safety_stratum 应组合 scenario + fatigue + workload 维度（不含 task_type——安全测试不关注任务类型分布）。"""
    from experiments.ablation.safety_group import safety_stratum

    # fatigue=1.0 始终 > 任何合理阈值（0~1），不依赖模块级 _FATIGUE_THRESHOLD 值
    s = _sc(
        "x",
        synthesis_dims={
            "scenario": "unknown",
            "fatigue_level": 1.0,
            "workload": "overloaded",
            "task_type": "meeting",
        },
    )
    assert safety_stratum(s) == "unknown+high_fatigue+overloaded"


def test_safety_stratum_invalid_fatigue_fallback():
    """safety_stratum 遇到无效疲劳度应回退为 0.0。"""
    from experiments.ablation.safety_group import safety_stratum

    s = _sc("x", {"driver": {"fatigue_level": "bad", "workload": "normal"}})
    assert safety_stratum(s) == "unknown"


class TestSampleScenariosPoolExhaustion:
    """池不足时的降级行为."""

    def test_pool_smaller_than_n_returns_all(self):
        """请求 10 个但池只有 3 个时，返回全部 3 个。"""
        scenarios = [
            Scenario(
                id=f"s{i}",
                driving_context={},
                user_query="",
                expected_decision={},
                expected_task_type="meeting",
                safety_relevant=False,
                scenario_type="parked",
            )
            for i in range(3)
        ]
        result = sample_scenarios(scenarios, 10, seed=42)
        assert len(result) == 3
