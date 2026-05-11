"""测试 LLM JSON 输出结构化验证模型."""

import pytest
from pydantic import ValidationError

from app.agents.workflow import (
    ContextOutput,
    LLMJsonResponse,
    StrategyOutput,
    TaskOutput,
)


class TestLLMJsonResponse:
    def test_extra_fields_rejected(self):
        """Given 含额外字段的 LLM 输出, When from_llm, then 抛出校验异常并兜底."""
        text = '{"raw":"aaa","extra_field":"x"}'
        result = LLMJsonResponse.from_llm(text)
        assert result.raw == text

    def test_from_llm_valid_json(self):
        """Given 合法 JSON, When from_llm, then 正确解析."""
        result = LLMJsonResponse.from_llm('{"raw":"ok"}')
        assert result.raw == '{"raw":"ok"}'

    def test_from_llm_codeblock(self):
        """Given 代码块包裹的 JSON, When from_llm, then 去除代码标记."""
        text = '```json\n{"raw":"hello"}\n```'
        result = LLMJsonResponse.from_llm(text)
        assert result.raw == text

    def test_from_llm_invalid_json(self):
        """Given 非 JSON 输出, When from_llm, then 返回仅含 raw 的实例."""
        text = "你好世界"
        result = LLMJsonResponse.from_llm(text)
        assert result.raw == text

    def test_from_llm_not_dict(self):
        """Given JSON 数组, When from_llm, then 返回仅含 raw 的实例."""
        text = '["a","b"]'
        result = LLMJsonResponse.from_llm(text)
        assert result.raw == text


class TestContextOutput:
    def test_valid_minimal(self):
        """Given 最小合法输入, When validate, then 使用默认值."""
        obj = ContextOutput()
        assert obj.scenario == ""
        assert obj.driver_state == {}
        assert obj.conversation_history is None

    def test_extra_fields_rejected(self):
        """Given 含额外字段的输入, When validate, then 抛出 ValidationError."""
        data = {"scenario": "highway", "unknown_field": 42}
        try:
            ContextOutput.model_validate(data)
            pytest.fail("应抛出 ValidationError")
        except ValidationError:
            pass

    def test_all_fields_default(self):
        """Given 空输入, When validate, then 全部字段使用默认值."""
        obj = ContextOutput()
        assert obj.model_dump() == {
            "scenario": "",
            "driver_state": {},
            "spatial": {},
            "traffic": {},
            "current_datetime": "",
            "related_events": [],
            "conversation_history": None,
        }


class TestTaskOutput:
    def test_valid_full(self):
        """Given 完整合法输入, When validate, then 字段正确映射."""
        obj = TaskOutput(
            type="meeting", confidence=0.9, description="开会", entities=["会议室"]
        )
        assert obj.type == "meeting"
        assert obj.confidence == 0.9
        assert obj.description == "开会"
        assert obj.entities == ["会议室"]

    def test_extra_rejected(self):
        """Given 含额外字段的输入, When validate, then 抛出 ValidationError."""
        data = {"type": "meeting", "unknown": True}
        try:
            TaskOutput.model_validate(data)
            pytest.fail("应抛出 ValidationError")
        except ValidationError:
            pass


class TestStrategyOutput:
    def test_valid_minimal(self):
        """Given 最小合法输入, When validate, then 使用默认值."""
        obj = StrategyOutput()
        assert obj.should_remind is True
        assert obj.timing == "now"
        assert obj.delay_seconds == 300
        assert obj.postpone is False

    def test_extra_rejected(self):
        """Given 含额外字段的输入, When validate, then 抛出 ValidationError."""
        data = {"should_remind": True, "unknown": "x"}
        try:
            StrategyOutput.model_validate(data)
            pytest.fail("应抛出 ValidationError")
        except ValidationError:
            pass
