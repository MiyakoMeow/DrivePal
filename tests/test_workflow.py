"""工作流工具函数测试."""

from app.agents.workflow import _extract_reminder_content, _is_relevant_strategy


def test_extract_reminder_content_from_string() -> None:
    """给定字符串值返回字符串本身."""
    result = _extract_reminder_content({"reminder_content": "hello"})
    assert result == "hello"


def test_extract_reminder_content_from_dict_value() -> None:
    """给定 dict 值提取 text 字段."""
    result = _extract_reminder_content({"reminder_content": {"text": "hello"}})
    assert result == "hello"


def test_extract_reminder_content_from_dict_content_key() -> None:
    """Dict 值用 content 字段兜底."""
    result = _extract_reminder_content({"reminder_content": {"content": "world"}})
    assert result == "world"


def test_extract_reminder_content_dict_missing_text_continues() -> None:
    """Dict 值无 text/content 时继续尝试后续 key 而非提前返回."""
    result = _extract_reminder_content(
        {"reminder_content": {"other": "x"}, "content": "fallback"}
    )
    assert result == "fallback"


def test_extract_reminder_content_fallback() -> None:
    """所有 key 缺失时返回默认值."""
    result = _extract_reminder_content({})
    assert result == "无提醒内容"


def test_extract_reminder_content_remind_key() -> None:
    """remind_content key 也生效."""
    result = _extract_reminder_content({"remind_content": "remind me"})
    assert result == "remind me"


def test_is_relevant_strategy_filters_empty_dict() -> None:
    """空 dict 视为不相关."""
    assert _is_relevant_strategy({}) is False


def test_is_relevant_strategy_filters_empty_list() -> None:
    """空 list 视为不相关."""
    assert _is_relevant_strategy([]) is False


def test_is_relevant_strategy_keeps_non_empty() -> None:
    """非空值视为相关."""
    assert _is_relevant_strategy({"key": "val"}) is True
    assert _is_relevant_strategy([1, 2, 3]) is True
    assert _is_relevant_strategy("string") is True
    assert _is_relevant_strategy(42) is True


def test_is_relevant_strategy_filters_none() -> None:
    """None 值视为不相关（避免 strategies 中的空值进入 prompt）。"""
    assert _is_relevant_strategy(None) is False


def test_is_relevant_strategy_keeps_other_falsy() -> None:
    """除 None 外的 falsy 值（0/False）视为相关（非容器不过滤）。"""
    assert _is_relevant_strategy(0) is True
    val = False
    assert _is_relevant_strategy(val) is True
