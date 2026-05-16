"""消融实验正确性修复回归测试."""


def test_has_visual_content_no_stages():
    from experiments.ablation.feedback_simulator import has_visual_content

    assert (
        has_visual_content({"reminder_content": {"display_text": "前方拥堵"}}) is True
    )
    assert has_visual_content({"reminder_content": {"display_text": ""}}) is False
    assert has_visual_content({"reminder_content": {}}) is False
    assert has_visual_content({}) is False


def test_export_restore_feedback_state_roundtrip():
    from experiments.ablation.feedback_simulator import (
        _current_delta,
        _recent_feedback,
        export_state,
        restore_state,
    )

    try:
        _current_delta[("test_user", "meeting")] = 0.25
        _recent_feedback[("test_user", "meeting")] = [1, -1, 1]

        state = export_state()
        delta_map = {
            (d["user_id"], d["task_type"]): d["value"] for d in state["_current_delta"]
        }
        fb_map = {
            (d["user_id"], d["task_type"]): d["value"]
            for d in state["_recent_feedback"]
        }
        assert delta_map[("test_user", "meeting")] == 0.25
        assert fb_map[("test_user", "meeting")] == [1, -1, 1]

        _current_delta.clear()
        _recent_feedback.clear()
        restore_state(state)
        assert _current_delta[("test_user", "meeting")] == 0.25
        assert _recent_feedback[("test_user", "meeting")] == [1, -1, 1]
    finally:
        _current_delta.clear()
        _recent_feedback.clear()


def test_safety_stratum_handles_non_float_fatigue():
    """给定 synthesis_dims 中 fatigue_level 为非数字字符串，safety_stratum 不抛异常并回退。"""
    from experiments.ablation.safety_group import safety_stratum
    from experiments.ablation.types import Scenario

    s = Scenario(
        id="test",
        driving_context={},
        user_query="test",
        expected_decision={},
        expected_task_type="other",
        safety_relevant=True,
        scenario_type="city_driving",
        synthesis_dims={
            "scenario": "highway",
            "fatigue_level": "invalid",
            "workload": "normal",
        },
    )
    result = safety_stratum(s)
    assert "highway" in result
    assert "high_fatigue" not in result  # invalid 回退 0.5，不大于阈值


def test_pers_stratum_uses_synthesis_dims():
    """给定 synthesis_dims.task_type 与 expected_task_type 不同，pers_stratum 使用合成维度。"""
    from experiments.ablation.personalization_group import pers_stratum
    from experiments.ablation.types import Scenario

    s = Scenario(
        id="test",
        driving_context={},
        user_query="test",
        expected_decision={},
        expected_task_type="llm_may_be_wrong",
        safety_relevant=False,
        scenario_type="city_driving",
        synthesis_dims={"scenario": "city_driving", "task_type": "meeting"},
    )
    assert pers_stratum(s) == "meeting"
