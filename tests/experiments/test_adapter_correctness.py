"""VehicleMemBench 适配器正确性测试."""

from experiments.vehicle_mem_bench.adapter import (
    _EN_PREFERENCE_KEYWORDS,
    _PREFERENCE_KEYWORDS,
    _resolve_strength,
)


class TestPreferenceKeywords:
    """偏好关键词中英文匹配."""

    def test_cn_keywords_detect_chinese_preference(self):
        content = "用户设置空调温度为24度"
        assert _resolve_strength(content) == 5

    def test_cn_keywords_non_preference_returns_default(self):
        content = "今天天气不错"
        assert _resolve_strength(content) == 3

    def test_en_keywords_detect_english_preference(self):
        content = "Gary prefers green for the instrument panel"
        assert _resolve_strength(content) == 5

    def test_en_keywords_change_detected(self):
        content = "Can you change the seat position?"
        assert _resolve_strength(content) == 5

    def test_en_keywords_set_detected(self):
        content = "Set the volume to 30"
        assert _resolve_strength(content) == 5

    def test_en_keywords_switch_detected(self):
        content = "Switch to FM radio"
        assert _resolve_strength(content) == 5

    def test_en_non_preference_returns_default(self):
        content = "The weather is nice today"
        assert _resolve_strength(content) == 3

    def test_en_case_insensitive(self):
        content = "I PREFER the dark mode"
        assert _resolve_strength(content) == 5

    def test_en_adjust_detected(self):
        content = "Adjust the brightness please"
        assert _resolve_strength(content) == 5

    def test_en_want_detected(self):
        content = "I want cooler temperature"
        assert _resolve_strength(content) == 5
