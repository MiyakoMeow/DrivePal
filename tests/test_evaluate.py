"""Tests for the evaluate module (evaluation functions migrated from runner.py)."""

from app.experiment.runners.evaluate import (
    evaluate_semantic_accuracy,
    evaluate_context_relatedness,
    infer_intent,
)


def test_infer_intent_schedule_check():
    assert infer_intent("今天有什么安排？") == "schedule_check"


def test_infer_intent_event_add():
    assert infer_intent("提醒我下午三点开会") == "event_add"


def test_infer_intent_event_delete():
    assert infer_intent("删除这个事件") == "event_delete"


def test_infer_intent_general():
    assert infer_intent("你好") == "general"


def test_semantic_accuracy_positive():
    score = evaluate_semantic_accuracy(
        "提醒我明天开会", "schedule_check", "明天有个会议安排"
    )
    assert score > 0


def test_semantic_accuracy_handles_raw_json():
    raw = '{"reasoning": "用户查询日程", "should_remind": false}'
    score = evaluate_semantic_accuracy("明天有什么安排", "schedule_check", raw)
    assert score > 0


def test_context_relatedness_schedule_check():
    score = evaluate_context_relatedness(
        "明天有什么安排",
        "schedule_check",
        "你的日程安排如下：明天下午三点有个会议提醒",
    )
    assert score > 0
