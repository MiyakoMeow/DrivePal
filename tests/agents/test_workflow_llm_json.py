"""LLMJsonResponse 解析测试."""

from app.agents.workflow import LLMJsonResponse


class TestLLMJsonResponseFromLlm:
    """from_llm 应接受 LLM 返回的任意 JSON 字段."""

    def test_extra_fields_stored_in_data(self):
        """LLM 返回含 events/task/confidence 等 field 时，data 应非空。"""
        text = '{"events": [{"time": "10:00"}], "task": "shopping", "confidence": 0.9}'
        result = LLMJsonResponse.from_llm(text)
        assert result.data is not None
        assert result.data["task"] == "shopping"
        assert result.data["confidence"] == 0.9

    def test_decision_fields_stored_in_data(self):
        """Strategy 输出含 should_remind/timing 等时，data 应非空。"""
        text = '{"should_remind": false, "timing": "skip", "reason": "无需提醒"}'
        result = LLMJsonResponse.from_llm(text)
        assert result.data is not None
        assert result.data["should_remind"] is False

    def test_invalid_json_returns_none_data(self):
        """非法 JSON → data=None, raw 保留原文。"""
        text = "not json at all"
        result = LLMJsonResponse.from_llm(text)
        assert result.data is None
        assert result.raw == text

    def test_json_array_returns_none_data(self):
        """JSON 数组（非 dict）→ data=None。"""
        text = "[1, 2, 3]"
        result = LLMJsonResponse.from_llm(text)
        assert result.data is None

    def test_markdown_wrapped_json_stored(self):
        """LLM 返回 markdown 代码块包裹的 JSON → 正确提取。"""
        text = '```json\n{"task": "meeting", "confidence": 0.8}\n```'
        result = LLMJsonResponse.from_llm(text)
        assert result.data is not None
        assert result.data["task"] == "meeting"
