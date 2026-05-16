"""消融实验正确性修复回归测试."""


def test_has_visual_content_no_stages():
    from experiments.ablation.feedback_simulator import has_visual_content

    assert has_visual_content({"reminder_content": {"display_text": "前方拥堵"}}) is True
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

    _current_delta[("test_user", "meeting")] = 0.25
    _recent_feedback[("test_user", "meeting")] = [1, -1, 1]

    state = export_state()
    assert state["_current_delta"]["test_user::meeting"] == 0.25
    assert state["_recent_feedback"]["test_user::meeting"] == [1, -1, 1]

    _current_delta.clear()
    _recent_feedback.clear()
    restore_state(state)
    assert _current_delta[("test_user", "meeting")] == 0.25
    assert _recent_feedback[("test_user", "meeting")] == [1, -1, 1]

    _current_delta.clear()
    _recent_feedback.clear()
