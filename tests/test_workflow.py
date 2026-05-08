"""工作流工具函数测试."""

from app.agents.workflow import _extract_reminder_content


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
