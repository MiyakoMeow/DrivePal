import pytest
from app.experiment.runner import _infer_intent, INTENT_KEYWORDS


def test_intent_keywords_contains_chinese_and_english():
    assert "时间" in INTENT_KEYWORDS["schedule_check"]
    assert "schedule" in INTENT_KEYWORDS["schedule_check"]
    assert "添加" in INTENT_KEYWORDS["event_add"]
    assert "add" in INTENT_KEYWORDS["event_add"]


def test_infer_intent_with_chinese():
    assert _infer_intent("帮我查一下明天的日程") == "schedule_check"
    assert _infer_intent("提醒我下午三点开会") == "event_add"


def test_infer_intent_with_english():
    assert _infer_intent("what's on my schedule tomorrow") == "schedule_check"
    assert _infer_intent("remind me to call John at 3pm") == "event_add"


def test_time_decay_weight():
    from app.experiment.runner import _compute_time_decay
    from datetime import datetime, timedelta

    now = datetime.now()

    # 0天前 = 权重1.0
    assert _compute_time_decay(now) == pytest.approx(1.0, rel=0.1)

    # 7天前 ≈ e^(-1) ≈ 0.368 (指数衰减)
    week_ago = now - timedelta(days=7)
    weight = _compute_time_decay(week_ago)
    assert 0.3 < weight < 0.4


def test_negative_pattern_detection():
    from app.experiment.runner import _has_negative_pattern

    # 肯定句
    assert not _has_negative_pattern("帮我查一下明天的日程")
    assert not _has_negative_pattern("提醒我下午开会")

    # 否定句
    assert _has_negative_pattern("不要提醒我")
    assert _has_negative_pattern("取消明天的会议")
    assert _has_negative_pattern("don't remind me")
    assert _has_negative_pattern("cancel the meeting")


def test_multi_turn_context_weight():
    from app.experiment.runner import _compute_context_weight

    assert _compute_context_weight(current_turn=1, last_turn=1) == 1.0
    assert _compute_context_weight(current_turn=2, last_turn=1) == 0.8
    assert _compute_context_weight(current_turn=3, last_turn=1) <= 0.6


def test_evaluate_semantic_with_rules():
    from app.experiment.runner import _evaluate_semantic_accuracy

    # 相同意图 = 高分
    score1 = _evaluate_semantic_accuracy(
        input_text="明天有什么日程",
        output="明天9点有个会议",
        expected_type="schedule_check",
    )
    assert score1 >= 0.4  # 意图匹配占40%

    # 否定句处理
    score2 = _evaluate_semantic_accuracy(
        input_text="不要提醒我开会",
        output="好的，已取消提醒",
        expected_type="event_delete",
    )
    assert score2 >= 0.2  # 否定模式匹配占20%
