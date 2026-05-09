"""测试 OutputRouter 多格式输出与通道路由."""

import pytest

from app.agents.outputs import (
    InterruptLevel,
    MultiFormatContent,
    OutputChannel,
    OutputRouter,
)


class TestMultiFormatContent:
    def test_all_fields_populated(self):
        """Given 完整字段, When 构造 MultiFormatContent, Then 所有字段正确."""
        rc = MultiFormatContent(
            speakable_text="3点开会",
            display_text="会议 · 15:00",
            detailed="会议提醒：下午3点",
            channel=OutputChannel.AUDIO,
            interrupt_level=InterruptLevel.NORMAL,
        )
        assert rc.speakable_text == "3点开会"
        assert rc.display_text == "会议 · 15:00"
        assert rc.channel == OutputChannel.AUDIO
        assert rc.interrupt_level == InterruptLevel.NORMAL

    def test_model_dump_serializes_enums(self):
        """Given MultiFormatContent, When model_dump(), Then 枚举序列化为字符串/数值."""
        rc = MultiFormatContent(
            speakable_text="3点开会",
            display_text="会议",
            detailed="会议提醒",
            channel=OutputChannel.AUDIO,
            interrupt_level=InterruptLevel.URGENT_NORMAL,
        )
        d = rc.model_dump()
        assert d["channel"] == "audio"
        assert d["interrupt_level"] == 1


class TestOutputRouterSpeakableFallback:
    def test_llm_provided_speakable_used_directly(self):
        """Given LLM 已生成 speakable_text, When OutputRouter, Then 直接使用."""
        decision = {
            "should_remind": True,
            "reminder_content": {
                "speakable_text": "3点开会",
                "display_text": "会议15点",
                "detailed": "完整文本很长很长超过15字限制",
            },
        }
        router = OutputRouter()
        result = router.route(decision, scenario="city_driving", rules_result={})
        assert result.speakable_text == "3点开会"

    def test_fallback_truncation_from_detailed(self):
        """Given LLM 未生成 speakable_text, When OutputRouter, Then 从 detailed 截断."""
        decision = {
            "should_remind": True,
            "reminder_content": {
                "detailed": "会议提醒下午3点公司3楼会议室确认参加",
            },
        }
        router = OutputRouter()
        result = router.route(decision, scenario="city_driving", rules_result={})
        assert len(result.speakable_text) <= 15
        assert not result.speakable_text.endswith("。")

    def test_fallback_empty_all_default_text(self):
        """Given 所有内容为空, When OutputRouter, Then 兜底文本."""
        decision = {
            "should_remind": True,
            "reminder_content": {"detailed": ""},
        }
        router = OutputRouter()
        result = router.route(decision, scenario="city_driving", rules_result={})
        assert result.speakable_text == "提醒"

    def test_reminder_content_as_string(self):
        """Given reminder_content 为纯字符串（非 dict）, When OutputRouter, Then 兜底处理."""
        decision = {
            "should_remind": True,
            "reminder_content": "纯文本提醒内容",
        }
        router = OutputRouter()
        result = router.route(decision, scenario="city_driving", rules_result={})
        assert len(result.speakable_text) <= 15


class TestOutputRouterInterruptLevel:
    def test_emergency_is_immediate(self):
        """Given LLM 标记 is_emergency=true, When OutputRouter, Then interrupt_level=IMMEDIATE."""
        decision = {
            "should_remind": True,
            "is_emergency": True,
            "reminder_content": {"detailed": "xx"},
        }
        router = OutputRouter()
        result = router.route(decision, scenario="city_driving", rules_result={})
        assert result.interrupt_level == InterruptLevel.URGENT_IMMEDIATE

    def test_only_urgent_is_urgent_normal(self):
        """Given rules_result.only_urgent=true, When OutputRouter, Then URGENT_NORMAL."""
        decision = {
            "should_remind": True,
            "reminder_content": {"detailed": "xx"},
        }
        router = OutputRouter()
        result = router.route(
            decision,
            scenario="city_driving",
            rules_result={"only_urgent": True},
        )
        assert result.interrupt_level == InterruptLevel.URGENT_NORMAL

    def test_normal_is_zero(self):
        decision = {
            "should_remind": True,
            "reminder_content": {"detailed": "xx"},
        }
        router = OutputRouter()
        result = router.route(decision, scenario="city_driving", rules_result={})
        assert result.interrupt_level == InterruptLevel.NORMAL

    def test_emergency_overrides_only_urgent(self):
        """Given 同时 is_emergency + only_urgent, When OutputRouter, Then IMMEDIATE 优先."""
        decision = {
            "should_remind": True,
            "is_emergency": True,
            "reminder_content": {"detailed": "xx"},
        }
        router = OutputRouter()
        result = router.route(
            decision,
            scenario="city_driving",
            rules_result={"only_urgent": True},
        )
        assert result.interrupt_level == InterruptLevel.URGENT_IMMEDIATE


class TestOutputRouterChannel:
    def test_rules_allowed_channels_takes_precedence(self):
        """Given rules_result 有 allowed_channels, When OutputRouter, Then 取第一优先."""
        decision = {
            "should_remind": True,
            "reminder_content": {"detailed": "xx"},
        }
        router = OutputRouter()
        result = router.route(
            decision,
            scenario="highway",
            rules_result={"allowed_channels": [OutputChannel.AUDIO, OutputChannel.VISUAL]},
        )
        assert result.channel == OutputChannel.AUDIO

    def test_channel_from_string(self):
        """Given allowed_channels 为字符串列表, When OutputRouter, Then 正确转换枚举."""
        decision = {
            "should_remind": True,
            "reminder_content": {"detailed": "xx"},
        }
        router = OutputRouter()
        result = router.route(
            decision,
            scenario="parked",
            rules_result={"allowed_channels": ["visual", "audio"]},
        )
        assert result.channel == OutputChannel.VISUAL

    def test_empty_allowed_channels_defaults_visual(self):
        decision = {
            "should_remind": True,
            "reminder_content": {"detailed": "xx"},
        }
        router = OutputRouter()
        result = router.route(
            decision,
            scenario="city_driving",
            rules_result={"allowed_channels": []},
        )
        assert result.channel == OutputChannel.VISUAL

    def test_none_allowed_channels_defaults_visual(self):
        decision = {
            "should_remind": True,
            "reminder_content": {"detailed": "xx"},
        }
        router = OutputRouter()
        result = router.route(decision, scenario="city_driving", rules_result={})
        assert result.channel == OutputChannel.VISUAL
