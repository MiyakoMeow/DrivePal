"""测试 LLM JSON 输出结构化验证模型."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.agents.workflow import (
    AgentWorkflow,
    ContextOutput,
    JointDecisionOutput,
    LLMJsonResponse,
    StrategyOutput,
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


class TestJointDecisionOutput:
    def test_valid_full(self):
        """完整合法输入，字段正确映射。"""
        obj = JointDecisionOutput(
            task_type="meeting",
            confidence=0.9,
            entities=[{"time": "15:00", "location": "3F"}],
            decision={"should_remind": True, "timing": "now"},
        )
        assert obj.task_type == "meeting"
        assert obj.confidence == 0.9
        assert len(obj.entities) == 1
        assert obj.decision["should_remind"] is True

    def test_alias_task_type(self):
        """task_type key 通过 AliasChoices 接受。"""
        data = {"task_type": "travel", "decision": {}}
        obj = JointDecisionOutput.model_validate(data)
        assert obj.task_type == "travel"

    def test_alias_type(self):
        """旧 type key 也通过 AliasChoices 接受。"""
        data = {"type": "shopping", "decision": {}}
        obj = JointDecisionOutput.model_validate(data)
        assert obj.task_type == "shopping"

    def test_alias_conf(self):
        """conf key 也通过 AliasChoices 接受。"""
        data = {"confidence": 0.0, "type": "travel", "decision": {}}
        obj1 = JointDecisionOutput.model_validate(data)
        assert obj1.confidence == 0.0

        data2 = {"conf": 0.8, "type": "travel", "decision": {}}
        obj2 = JointDecisionOutput.model_validate(data2)
        assert obj2.confidence == 0.8

    def test_extra_rejected(self):
        """含额外字段 → ValidationError。"""
        data = {"task_type": "meeting", "unknown": True}
        try:
            JointDecisionOutput.model_validate(data)
            pytest.fail("应抛 ValidationError")
        except ValidationError:
            pass


class TestStrategyOutput:
    def test_valid_minimal(self):
        """最小合法输入，使用默认值。"""
        obj = StrategyOutput()
        assert obj.should_remind is True
        assert obj.timing == "now"
        assert obj.delay_seconds == 300
        assert obj.postpone is False

    def test_extra_rejected(self):
        """含额外字段 → ValidationError。"""
        data = {"should_remind": True, "unknown": "x"}
        try:
            StrategyOutput.model_validate(data)
            pytest.fail("应抛 ValidationError")
        except ValidationError:
            pass


class TestWorkflowValidationPath:
    @pytest.mark.asyncio
    async def test_context_node_validation_success(self, tmp_path):
        """LLM 返回合法 JSON 时走 validate 分支，不抛异常。"""
        workflow = AgentWorkflow(data_dir=tmp_path, memory_module=MagicMock())
        workflow._call_llm_json = AsyncMock(
            return_value=LLMJsonResponse(
                raw='{"scenario":"highway","driver_state":{},'
                '"spatial":{},"traffic":{},'
                '"current_datetime":"2026-01-01"}',
            )
        )
        result = await workflow._context_node(
            {
                "original_query": "test",
                "context": {},
                "task": None,
                "decision": None,
                "result": None,
                "event_id": None,
                "driving_context": None,
                "stages": None,
                "session_id": None,
            }
        )
        assert "context" in result

    @pytest.mark.asyncio
    async def test_joint_decision_node_validation_success(self, tmp_path):
        """JointDecision 节点 validate 分支不抛异常。"""
        workflow = AgentWorkflow(data_dir=tmp_path, memory_module=MagicMock())
        workflow._call_llm_json = AsyncMock(
            return_value=LLMJsonResponse.from_llm(
                '{"task_type":"meeting","confidence":0.9,'
                '"entities":[],'
                '"decision":{"should_remind":true,"timing":"now"}}',
            )
        )
        result = await workflow._joint_decision_node(
            {
                "original_query": "test",
                "context": {"scenario": "city_driving"},
                "task": None,
                "decision": None,
                "result": None,
                "event_id": None,
                "driving_context": None,
                "stages": None,
            }
        )
        assert "task" in result
        assert "decision" in result
        assert result["task"]["type"] == "meeting"

    @pytest.mark.asyncio
    async def test_joint_decision_node_fallback_on_bad_json(self, tmp_path):
        """LLM 返回非法 JSON → fallback 分支，不抛异常。"""
        workflow = AgentWorkflow(data_dir=tmp_path, memory_module=MagicMock())
        workflow._call_llm_json = AsyncMock(
            return_value=LLMJsonResponse(raw="not json"),
        )
        result = await workflow._joint_decision_node(
            {
                "original_query": "test",
                "context": {},
                "task": None,
                "decision": None,
                "result": None,
                "event_id": None,
                "driving_context": None,
                "stages": None,
            }
        )
        assert "task" in result
        assert "decision" in result


class TestFormatConstraintsHint:
    """_format_constraints_hint 纯单元测试。"""

    def test_none_context(self):
        AgentWorkflow._format_constraints_hint(None) == ""

    def test_empty_context(self):
        AgentWorkflow._format_constraints_hint({}) == ""

    def test_no_constraints(self):
        AgentWorkflow._format_constraints_hint({"scenario": "parked"}) == ""


class TestFormatPreferenceHint:
    """_format_preference_hint 纯单元测试。"""

    @pytest.mark.asyncio
    async def test_ablation_disabled(self, tmp_path):
        from app.agents.workflow import set_ablation_disable_feedback
        set_ablation_disable_feedback(True)
        workflow = AgentWorkflow(data_dir=tmp_path, memory_module=MagicMock())
        result = await workflow._format_preference_hint()
        assert result == ""
        set_ablation_disable_feedback(False)

    @pytest.mark.asyncio
    async def test_no_weights(self, tmp_path):
        workflow = AgentWorkflow(data_dir=tmp_path, memory_module=MagicMock())
        workflow._strategies_store.read = AsyncMock(return_value={})
        assert await workflow._format_preference_hint() == ""

    @pytest.mark.asyncio
    async def test_high_weight(self, tmp_path):
        workflow = AgentWorkflow(data_dir=tmp_path, memory_module=MagicMock())
        workflow._strategies_store.read = AsyncMock(
            return_value={"reminder_weights": {"meeting": 0.7}}
        )
        result = await workflow._format_preference_hint()
        assert "meeting" in result and "优先处理" in result

    @pytest.mark.asyncio
    async def test_low_weight(self, tmp_path):
        workflow = AgentWorkflow(data_dir=tmp_path, memory_module=MagicMock())
        workflow._strategies_store.read = AsyncMock(
            return_value={"reminder_weights": {"travel": 0.55}}
        )
        result = await workflow._format_preference_hint()
        assert "travel" in result and "略偏好" in result

    @pytest.mark.asyncio
    async def test_all_below_05(self, tmp_path):
        workflow = AgentWorkflow(data_dir=tmp_path, memory_module=MagicMock())
        workflow._strategies_store.read = AsyncMock(
            return_value={"reminder_weights": {"a": 0.5, "b": 0.5}}
        )
        assert await workflow._format_preference_hint() == ""

    @pytest.mark.asyncio
    async def test_non_dict_weights(self, tmp_path):
        workflow = AgentWorkflow(data_dir=tmp_path, memory_module=MagicMock())
        workflow._strategies_store.read = AsyncMock(
            return_value={"reminder_weights": "invalid"}
        )
        assert await workflow._format_preference_hint() == ""

    @pytest.mark.asyncio
    async def test_mixed_numeric_types(self, tmp_path):
        workflow = AgentWorkflow(data_dir=tmp_path, memory_module=MagicMock())
        workflow._strategies_store.read = AsyncMock(
            return_value={"reminder_weights": {"meeting": 0.7, "travel": 1}}
        )
        result = await workflow._format_preference_hint()
        assert "travel" in result
