"""消融实验方法论优化测试."""

import json

from experiments.ablation.config import STAGE_TIMEOUT, load_stage_timeouts
from experiments.ablation.metrics import bootstrap_ci, wilcoxon_test
from experiments.ablation.scenario_synthesizer import (
    _compute_safety_relevant,
    _parse_dims_from_id,
)
from experiments.ablation.types import JudgeScores, Scenario, Variant, VariantResult


class TestComputeSafetyRelevant:
    """合成维度安全分类."""

    def test_highway_always_safety(self):
        assert _compute_safety_relevant(
            {"scenario": "highway", "fatigue_level": 0.1, "workload": "low"}
        )

    def test_city_driving_normal_not_safety(self):
        assert not _compute_safety_relevant(
            {"scenario": "city_driving", "fatigue_level": 0.1, "workload": "normal"}
        )

    def test_high_fatigue_is_safety(self):
        assert _compute_safety_relevant(
            {"scenario": "city_driving", "fatigue_level": 0.9, "workload": "normal"}
        )

    def test_overloaded_is_safety(self):
        assert _compute_safety_relevant(
            {"scenario": "traffic_jam", "fatigue_level": 0.1, "workload": "overloaded"}
        )

    def test_parked_low_fatigue_not_safety(self):
        assert not _compute_safety_relevant(
            {"scenario": "parked", "fatigue_level": 0.1, "workload": "low"}
        )


class TestParseDimsFromId:
    """从场景 id 解析合成维度."""

    def test_highway_id(self):
        result = _parse_dims_from_id("highway_0.1_low_meeting_true")
        assert result["scenario"] == "highway"
        assert result["fatigue_level"] == 0.1

    def test_city_driving_id_with_underscore(self):
        result = _parse_dims_from_id("city_driving_0.5_normal_travel_false")
        assert result["scenario"] == "city_driving"
        assert result["workload"] == "normal"

    def test_unknown_prefix_returns_empty(self):
        assert _parse_dims_from_id("unknown_0.1_low_meeting_true") == {}


class TestBootstrapCI:
    """Bootstrap 置信区间."""

    def test_significant_difference(self):
        group_a = [4.0, 5.0, 4.0, 5.0, 4.0]
        group_b = [2.0, 1.0, 2.0, 1.0, 2.0]
        result = bootstrap_ci(group_a, group_b)
        assert result["significant"]
        assert result["ci_lower"] > 0

    def test_no_difference(self):
        group = [3.0, 3.0, 3.0, 3.0, 3.0]
        result = bootstrap_ci(group, group)
        assert not result["significant"]

    def test_empty_groups(self):
        result = bootstrap_ci([], [])
        assert not result["significant"]


class TestWilcoxonTest:
    """Wilcoxon signed-rank test."""

    def _make_scores(
        self,
        baseline_scores: list[int],
        variant_scores: list[int],
        variant_name: str,
    ) -> list[JudgeScores]:
        scores = []
        for i, s in enumerate(baseline_scores):
            scores.append(
                JudgeScores(
                    scenario_id=f"s{i}",
                    variant=Variant.FULL,
                    safety_score=3,
                    reasonableness_score=3,
                    overall_score=s,
                    violation_flags=[],
                    explanation="",
                )
            )
        for i, s in enumerate(variant_scores):
            scores.append(
                JudgeScores(
                    scenario_id=f"s{i}",
                    variant=Variant(variant_name),
                    safety_score=3,
                    reasonableness_score=3,
                    overall_score=s,
                    violation_flags=[],
                    explanation="",
                )
            )
        return scores

    def test_paired_comparison(self):
        baseline = [4, 5, 4, 5, 4]
        variant = [2, 3, 2, 3, 2]
        scores = self._make_scores(baseline, variant, "no-rules")
        result = wilcoxon_test(scores)
        assert "no-rules" in result
        assert result["no-rules"]["n_pairs"] == 5

    def test_custom_key_fn_groups_by_composite_key(self):
        """给定自定义 key_fn，当 wilcoxon_test，则应按自定义键配对."""
        scores = []
        for i in range(5):
            scores.append(JudgeScores(f"s{i}", Variant.FULL, 3, 3, 4 + i, [], ""))
            scores.append(JudgeScores(f"s{i}", Variant.NO_RULES, 3, 3, 2, [], ""))
        result = wilcoxon_test(scores, key_fn=lambda s: f"{s.scenario_id}:r0")
        assert "no-rules" in result
        assert result["no-rules"]["n_pairs"] == 5


class TestStratumFunctions:
    """分层键使用合成维度."""

    def test_safety_stratum_with_dims(self):
        from experiments.ablation.safety_group import safety_stratum

        s = Scenario(
            id="highway_0.9_low_meeting_true",
            driving_context={},
            user_query="",
            expected_decision={},
            expected_task_type="meeting",
            safety_relevant=True,
            scenario_type="highway",
            synthesis_dims={
                "scenario": "highway",
                "fatigue_level": 0.9,
                "workload": "low",
                "task_type": "meeting",
                "has_passengers": "true",
            },
        )
        key = safety_stratum(s)
        assert key == "highway+high_fatigue"

    def test_arch_stratum_with_dims(self):
        from experiments.ablation.architecture_group import arch_stratum

        s = Scenario(
            id="parked_0.1_normal_shopping_false",
            driving_context={},
            user_query="",
            expected_decision={},
            expected_task_type="shopping",
            safety_relevant=False,
            scenario_type="parked",
            synthesis_dims={
                "scenario": "parked",
                "fatigue_level": 0.1,
                "workload": "normal",
                "task_type": "shopping",
                "has_passengers": "false",
            },
        )
        assert arch_stratum(s) == "parked:shopping"

    def test_classify_complexity_highway_is_complex(self):
        from experiments.ablation.architecture_group import classify_complexity

        assert classify_complexity(
            {
                "scenario": "highway",
                "fatigue_level": 0.1,
                "workload": "low",
                "task_type": "meeting",
                "has_passengers": "true",
            }
        )

    def test_no_dims_fallback(self):
        from experiments.ablation.safety_group import safety_stratum

        s = Scenario(
            id="unknown",
            driving_context={},
            user_query="",
            expected_decision={},
            expected_task_type="meeting",
            safety_relevant=True,
            scenario_type="highway",
        )
        assert safety_stratum(s) == "highway"


class TestBuildStages:
    """个性化组动态轮数截断."""

    def test_full_32_produces_4_equal_stages(self):
        from experiments.ablation.personalization_group import _build_stages

        stages, available = _build_stages(32)
        assert available == 32
        assert len(stages) == 4
        assert stages[-1][2] == 32

    def test_less_than_32_truncates(self):
        from experiments.ablation.personalization_group import _build_stages

        stages, available = _build_stages(20)
        assert available == 20
        assert stages[-1][2] == 20

    def test_minimum_4_scenarios(self):
        from experiments.ablation.personalization_group import _build_stages

        stages, available = _build_stages(4)
        assert available == 4
        assert len(stages) == 4

    def test_below_minimum_raises(self):
        import pytest

        from experiments.ablation.personalization_group import _build_stages

        with pytest.raises(ValueError, match="≥4"):
            _build_stages(3)


class TestFormatRulesForJudge:
    """Judge 规则动态生成."""

    def test_generates_rule_descriptions(self):
        from app.agents.rules import SAFETY_RULES
        from experiments.ablation.judge import format_rules_for_judge

        text = format_rules_for_judge(SAFETY_RULES)
        assert "规则1" in text
        assert "priority=" in text
        assert "fatigue" in text.lower()
        assert "highway" in text.lower()

    def test_empty_rules_returns_empty(self):
        from experiments.ablation.judge import format_rules_for_judge

        assert format_rules_for_judge([]) == ""

    def test_rule_count_matches_safety_rules(self):
        from app.agents.rules import SAFETY_RULES
        from experiments.ablation.judge import format_rules_for_judge

        text = format_rules_for_judge(SAFETY_RULES)
        assert text.count("规则") == len(SAFETY_RULES)


class TestMedianScores:
    """逐维度独立取中位数."""

    def test_per_dimension_median(self):
        from experiments.ablation.judge import _median_scores

        scores = [
            JudgeScores("s1", Variant.FULL, 5, 4, 5, [], "high"),
            JudgeScores("s1", Variant.FULL, 3, 5, 3, [], "mid"),
            JudgeScores("s1", Variant.FULL, 1, 3, 1, [], "low"),
        ]
        result = _median_scores(scores)
        assert len(result) == 1
        r = result[0]
        assert r.safety_score == 3
        assert r.reasonableness_score == 4
        assert r.overall_score == 3

    def test_single_score(self):
        from experiments.ablation.judge import _median_scores

        scores = [
            JudgeScores("s1", Variant.FULL, 4, 4, 4, [], "ok"),
        ]
        result = _median_scores(scores)
        assert len(result) == 1
        assert result[0].safety_score == 4

    def test_two_variants_grouped(self):
        from experiments.ablation.judge import _median_scores

        scores = [
            JudgeScores("s1", Variant.FULL, 5, 5, 5, [], ""),
            JudgeScores("s1", Variant.FULL, 3, 3, 3, [], ""),
            JudgeScores("s1", Variant.FULL, 1, 1, 1, [], ""),
            JudgeScores("s1", Variant.NO_RULES, 2, 2, 2, [], ""),
            JudgeScores("s1", Variant.NO_RULES, 4, 4, 4, [], ""),
            JudgeScores("s1", Variant.NO_RULES, 3, 3, 3, [], ""),
        ]
        result = _median_scores(scores)
        assert len(result) == 2
        full = [r for r in result if r.variant == Variant.FULL][0]
        no_rules = [r for r in result if r.variant == Variant.NO_RULES][0]
        assert full.safety_score == 3
        assert no_rules.safety_score == 3

    def test_even_count_takes_upper_median(self):
        """偶数条记录取上中位（index n//2）。"""
        from experiments.ablation.judge import _median_scores

        # 2 条记录，safety [1, 5]，上中位 index=1 → safety_score=5
        scores = [
            JudgeScores("s1", Variant.FULL, 1, 3, 3, [], "low"),
            JudgeScores("s1", Variant.FULL, 5, 4, 4, [], "high"),
        ]
        result = _median_scores(scores)
        assert len(result) == 1
        assert result[0].safety_score == 5  # [1,5] 上中位
        assert result[0].reasonableness_score == 4  # [3,4] 上中位
        assert result[0].overall_score == 4  # [3,4] 上中位

    def test_median_preserves_metadata_from_base_record(self):
        """violation_flags 和 explanation 取 overall 中位数对应记录的值。"""
        from experiments.ablation.judge import _median_scores

        scores = [
            JudgeScores("s1", Variant.FULL, 5, 5, 1, ["flag_a"], "low overall"),
            JudgeScores("s1", Variant.FULL, 3, 3, 3, ["flag_b"], "mid overall"),
            JudgeScores("s1", Variant.FULL, 1, 1, 5, ["flag_c"], "high overall"),
        ]
        result = _median_scores(scores)
        assert len(result) == 1
        r = result[0]
        # overall [1,3,5] 中位=3，对应第二条记录
        assert r.overall_score == 3
        assert r.violation_flags == ["flag_b"]
        assert r.explanation == "mid overall"


class TestJudgeOnlyCaching:
    """--judge-only 模式复用已有 scores.json."""

    async def test_try_load_existing_scores_returns_scores_when_complete(
        self, tmp_path
    ):
        """给定完整 scores.json，当 _try_load_existing_scores，则返回全部评分."""
        from experiments.ablation.cli import _try_load_existing_scores

        scores_data = {
            "scores": [
                {
                    "scenario_id": "s1",
                    "variant": "full",
                    "safety_score": 5,
                    "reasonableness_score": 4,
                    "overall_score": 4,
                    "violation_flags": [],
                    "explanation": "ok",
                },
                {
                    "scenario_id": "s1",
                    "variant": "no-rules",
                    "safety_score": 3,
                    "reasonableness_score": 3,
                    "overall_score": 3,
                    "violation_flags": [],
                    "explanation": "ok",
                },
            ]
        }
        path = tmp_path / "scores.json"
        path.write_text(json.dumps(scores_data))

        variant_results = [
            VariantResult("s1", Variant.FULL, {}, "", None, {}, 100),
            VariantResult("s1", Variant.NO_RULES, {}, "", None, {}, 100),
        ]
        loaded = await _try_load_existing_scores(path, variant_results)
        assert loaded is not None
        assert len(loaded) == 2

    async def test_try_load_existing_scores_returns_none_when_incomplete(
        self, tmp_path
    ):
        """给定不完整 scores.json，当 _try_load_existing_scores，则返回 None."""
        from experiments.ablation.cli import _try_load_existing_scores

        scores_data = {
            "scores": [
                {
                    "scenario_id": "s1",
                    "variant": "full",
                    "safety_score": 5,
                    "reasonableness_score": 4,
                    "overall_score": 4,
                    "violation_flags": [],
                    "explanation": "",
                }
            ]
        }
        path = tmp_path / "scores.json"
        path.write_text(json.dumps(scores_data))

        variant_results = [
            VariantResult("s1", Variant.FULL, {}, "", None, {}, 100),
            VariantResult("s1", Variant.NO_RULES, {}, "", None, {}, 100),
        ]
        loaded = await _try_load_existing_scores(path, variant_results)
        assert loaded is None

    async def test_try_load_existing_scores_returns_none_when_missing(self, tmp_path):
        """给定不存在的文件，当 _try_load_existing_scores，则返回 None."""
        from experiments.ablation.cli import _try_load_existing_scores

        loaded = await _try_load_existing_scores(tmp_path / "nope.json", [])
        assert loaded is None

    def test_safe_parse_judge_scores_damage_above_threshold_returns_none(self):
        """给定损坏率 6% > 5% 阈值，当 _safe_parse_judge_scores，则返回 None."""
        from experiments.ablation.cli import _safe_parse_judge_scores

        # 100 items, 6 bad → 6% > 5%
        items = [
            {
                "scenario_id": f"s{i}",
                "variant": "full",
                "safety_score": 5,
                "reasonableness_score": 4,
                "overall_score": 4,
            }
            for i in range(100)
        ]
        items[0].pop("safety_score")  # corrupt
        items[1].pop("safety_score")  # corrupt
        items[2].pop("safety_score")  # corrupt
        items[3].pop("safety_score")  # corrupt
        items[4].pop("safety_score")  # corrupt
        items[5].pop("safety_score")  # corrupt
        result = _safe_parse_judge_scores(items)
        assert result is None

    def test_safe_parse_judge_scores_damage_below_threshold_returns_valid(self):
        """给定损坏率 4% ≤ 5% 阈值，当 _safe_parse_judge_scores，则返回有效部分."""
        from experiments.ablation.cli import _safe_parse_judge_scores

        items = [
            {
                "scenario_id": f"s{i}",
                "variant": "full",
                "safety_score": 5,
                "reasonableness_score": 4,
                "overall_score": 4,
            }
            for i in range(100)
        ]
        items[0].pop("safety_score")  # corrupt
        items[1].pop("safety_score")  # corrupt
        items[2].pop("safety_score")  # corrupt
        items[3].pop("safety_score")  # corrupt
        result = _safe_parse_judge_scores(items)
        assert result is not None
        assert len(result) == 96


class TestObjectiveComplianceRate:
    """客观合规率——FULL/NO_PROB 按 modifications 判定，NO_RULES/NO_SAFETY 回退 Judge 率。"""

    async def test_objective_compliance_rate(self):
        from experiments.ablation.safety_group import compute_safety_metrics

        scores = [
            JudgeScores(
                scenario_id="s1",
                variant=Variant.FULL,
                safety_score=5,
                reasonableness_score=4,
                overall_score=4,
                violation_flags=[],
                explanation="",
            ),
            JudgeScores(
                scenario_id="s2",
                variant=Variant.FULL,
                safety_score=2,
                reasonableness_score=2,
                overall_score=2,
                violation_flags=["channel_violation"],
                explanation="",
            ),
        ]
        results = [
            VariantResult(
                scenario_id="s1",
                variant=Variant.FULL,
                decision={},
                result_text="",
                event_id=None,
                stages={},
                latency_ms=100,
                modifications=[],
            ),
            VariantResult(
                scenario_id="s2",
                variant=Variant.FULL,
                decision={},
                result_text="",
                event_id=None,
                stages={},
                latency_ms=100,
                modifications=["channel: audio->visual"],
            ),
        ]
        metrics = compute_safety_metrics(scores, results)
        assert "objective_compliance_rate" in metrics.get("full", {}), (
            "缺少 objective_compliance_rate"
        )
        full = metrics["full"]
        assert full["objective_compliance_rate"] == 0.5  # 1/2 compliant
        assert full["objective_compliant_n"] == 1

    async def test_objective_compliance_no_rules_fallback(self):
        from experiments.ablation.safety_group import compute_safety_metrics

        scores = [
            JudgeScores(
                scenario_id="s1",
                variant=Variant.NO_RULES,
                safety_score=5,
                reasonableness_score=4,
                overall_score=4,
                violation_flags=[],
                explanation="",
            ),
        ]
        results = [
            VariantResult(
                scenario_id="s1",
                variant=Variant.NO_RULES,
                decision={},
                result_text="",
                event_id=None,
                stages={},
                latency_ms=100,
                modifications=[],
            ),
        ]
        metrics = compute_safety_metrics(scores, results)
        nr = metrics["no-rules"]
        # NO_RULES 的 objective_compliance_rate 显式标为 None（不可得）
        assert nr["objective_compliance_rate"] is None
        # judge_compliance_rate 可用（safety_score>=4 → 1/1=1.0）
        assert nr["judge_compliance_rate"] == 1.0

    async def test_objective_compliance_no_safety_fallback(self):
        from experiments.ablation.safety_group import compute_safety_metrics

        scores = [
            JudgeScores(
                scenario_id="s1",
                variant=Variant.NO_SAFETY,
                safety_score=3,
                reasonableness_score=4,
                overall_score=4,
                violation_flags=[],
                explanation="",
            ),
        ]
        results = [
            VariantResult(
                scenario_id="s1",
                variant=Variant.NO_SAFETY,
                decision={},
                result_text="",
                event_id=None,
                stages={},
                latency_ms=100,
                modifications=[],
            ),
        ]
        metrics = compute_safety_metrics(scores, results)
        ns = metrics["no-safety"]
        # NO_SAFETY 的 objective_compliance_rate 显式标为 None（不可得）
        assert ns["objective_compliance_rate"] is None
        # judge_compliance_rate 可用（safety_score=3 < 4 → 0/1=0.0）
        assert ns["judge_compliance_rate"] == 0.0

    async def test_objective_compliance_no_prob_uses_modifications(self):
        from experiments.ablation.safety_group import compute_safety_metrics

        scores = [
            JudgeScores(
                scenario_id="s1",
                variant=Variant.NO_PROB,
                safety_score=5,
                reasonableness_score=4,
                overall_score=4,
                violation_flags=[],
                explanation="",
            ),
            JudgeScores(
                scenario_id="s2",
                variant=Variant.NO_PROB,
                safety_score=2,
                reasonableness_score=2,
                overall_score=2,
                violation_flags=["channel_violation"],
                explanation="",
            ),
        ]
        results = [
            VariantResult(
                scenario_id="s1",
                variant=Variant.NO_PROB,
                decision={},
                result_text="",
                event_id=None,
                stages={},
                latency_ms=100,
                modifications=[],
            ),
            VariantResult(
                scenario_id="s2",
                variant=Variant.NO_PROB,
                decision={},
                result_text="",
                event_id=None,
                stages={},
                latency_ms=100,
                modifications=["channel: audio->visual"],
            ),
        ]
        metrics = compute_safety_metrics(scores, results)
        np_metrics = metrics["no-prob"]
        assert np_metrics["objective_compliance_rate"] == 0.5
        assert np_metrics["objective_compliant_n"] == 1


class TestPrepareGroupScenariosComplexity:
    """预分配法应保证架构组含 complex 场景，安全/架构可重叠（user_id 隔离）。"""

    def test_prepare_group_scenarios_complexity(self):
        from experiments.ablation.architecture_group import classify_complexity
        from experiments.ablation.cli import _prepare_group_scenarios

        scenarios = _make_complexity_test_scenarios()

        result = _prepare_group_scenarios(
            scenarios, ["safety", "architecture", "personalization"], seed=42
        )

        arch_has_complex = any(
            classify_complexity(s.synthesis_dims)
            for s in result.get("architecture", [])
            if s.synthesis_dims
        )
        assert arch_has_complex, "架构组应至少含 1 个 complex 场景"
        assert len(result.get("architecture", [])) <= 50

        # 安全组与架构组可重叠——两组通过 user_id 隔离，
        # 同一场景出现在两组不污染实验数据
        safety_ids = {s.id for s in result.get("safety", [])}
        arch_ids = {s.id for s in result.get("architecture", [])}
        pers_ids = {s.id for s in result.get("personalization", [])}
        # 个性化组仍排除安全+架构已用 ID
        assert safety_ids.isdisjoint(pers_ids), "安全组和个性化组场景重叠"
        assert arch_ids.isdisjoint(pers_ids), "架构组和个性化组场景重叠"


def _make_complexity_test_scenarios():
    """202 场景：30 complex+safety, 22 complex-仅, 150 simple.

    总量须 > 50(安全) + 50(架构) + 32(个性化) = 132，
    确保三组均有场景可用。
    """
    scenarios: list[Scenario] = []
    for i in range(30):
        scenarios.append(
            Scenario(
                id=f"s{i:02d}",
                driving_context={},
                user_query="",
                expected_decision={},
                expected_task_type="other",
                safety_relevant=True,
                scenario_type="highway",
                synthesis_dims={
                    "scenario": "highway",
                    "fatigue_level": 0.9,
                    "workload": "overloaded",
                    "task_type": "other",
                    "has_passengers": "false",
                },
            )
        )
    for i in range(30, 52):
        scenarios.append(
            Scenario(
                id=f"s{i:02d}",
                driving_context={},
                user_query="",
                expected_decision={},
                expected_task_type="other",
                safety_relevant=False,
                scenario_type="highway",
                synthesis_dims={
                    "scenario": "highway",
                    "fatigue_level": 0.9,
                    "workload": "normal",
                    "task_type": "other",
                    "has_passengers": "false",
                },
            )
        )
    for i in range(52, 202):
        scenarios.append(
            Scenario(
                id=f"s{i:02d}",
                driving_context={},
                user_query="",
                expected_decision={},
                expected_task_type="other",
                safety_relevant=False,
                scenario_type="city_driving",
                synthesis_dims={
                    "scenario": "city_driving",
                    "fatigue_level": 0.1,
                    "workload": "normal",
                    "task_type": "other",
                    "has_passengers": "false",
                },
            )
        )
    return scenarios


class TestJudgeConcentrationDetection:
    """Judge 评分集中度检测."""

    def test_single_score_dominates_triggers_degradation(self):
        """80% 以上评分为同一值时标记退化。"""
        from experiments.ablation.judge import detect_judge_degradation

        scores = [
            JudgeScores(f"s{i}", Variant.FULL, 4, 4, 4, [], "") for i in range(9)
        ] + [JudgeScores(f"s{i}", Variant.FULL, 5, 5, 5, [], "") for i in range(9, 10)]
        result = detect_judge_degradation(scores)
        assert result["degraded"] is True
        assert "集中度" in result["warning"]

    def test_diverse_scores_no_concentration(self):
        """分数分布均匀时不触发集中度退化。"""
        from experiments.ablation.judge import detect_judge_degradation

        scores = [
            JudgeScores(f"s{i}", Variant.FULL, i + 1, i + 1, i + 1, [], "")
            for i in range(5)
        ]
        result = detect_judge_degradation(scores)
        assert result["degraded"] is False

    def test_exactly_80_percent_no_degradation(self):
        """恰好 80% 占比不触发集中度退化（严格 > 阈值）。"""
        from experiments.ablation.judge import detect_judge_degradation

        # 8/10 = 0.8 恰好等于 CONCENTRATION_THRESHOLD，严格 > 不触发
        scores = [
            JudgeScores(f"s{i}", Variant.FULL, 4, 4, 4, [], "") for i in range(8)
        ] + [JudgeScores(f"s{i}", Variant.FULL, 5, 5, 5, [], "") for i in range(8, 10)]
        result = detect_judge_degradation(scores)
        assert result["degraded"] is False


class TestStageTimeouts:
    """TOML 配置驱动阶段超时."""

    def test_default_keys_present(self):
        """模块级 STAGE_TIMEOUT 含三阶段且值均为正 float."""
        for key in ("context", "joint_decision", "execution"):
            assert key in STAGE_TIMEOUT, f"缺失阶段超时: {key}"
            assert isinstance(STAGE_TIMEOUT[key], float), f"{key} 非 float"
            assert STAGE_TIMEOUT[key] > 0, f"{key} 非正数"

    def test_load_parses_returns_float(self):
        """_load_stage_timeouts 返回 dict 值类型正确."""
        timeouts = load_stage_timeouts()
        for key in ("context", "joint_decision", "execution"):
            assert isinstance(timeouts[key], float)
