"""测试 ShortcutResolver."""

import pytest

from app.agents.pending import parse_duration, parse_time
from app.agents.shortcuts import ShortcutResolver


class TestParseDuration:
    def test_minutes(self):
        assert parse_duration("10分钟") == 600
        assert parse_duration("5分") == 300

    def test_half_hour(self):
        assert parse_duration("半小时") == 1800

    def test_hour(self):
        assert parse_duration("1小时") == 3600

    def test_invalid(self):
        assert parse_duration("abc") is None


class TestParseTime:
    def test_basic(self):
        assert parse_time("3点") == "15:00:00"

    def test_afternoon(self):
        assert parse_time("下午3点") == "15:00:00"

    def test_morning(self):
        assert parse_time("上午9点") == "09:00:00"

    def test_invalid(self):
        assert parse_time("abc") is None


class TestExactMatch:
    def test_remind_home(self):
        sr = ShortcutResolver()
        result = sr.resolve("提醒到家")
        assert result is not None
        assert result["type"] == "travel"
        assert result["location"] == "home"
        assert result["timing"] == "location"

    def test_cancel_reminder(self):
        sr = ShortcutResolver()
        result = sr.resolve("取消提醒")
        assert result is not None
        assert result["action"] == "cancel_last"


class TestPrefixMatch:
    def test_snooze_with_params(self):
        sr = ShortcutResolver()
        result = sr.resolve("延迟10分钟")
        assert result is not None
        assert result["action"] == "snooze"
        assert result["delay_seconds"] == 600

    def test_snooze_half_hour(self):
        sr = ShortcutResolver()
        result = sr.resolve("延迟半小时")
        assert result is not None
        assert result["delay_seconds"] == 1800


class TestNoMatchFallback:
    def test_complex_query_returns_none(self):
        sr = ShortcutResolver()
        result = sr.resolve("帮我查一下明天的天气")
        assert result is None
