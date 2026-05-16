"""工具执行器集成测试 — navigation 确认条件 + 工具结果注入。"""

from unittest.mock import AsyncMock, patch

import pytest

from app.tools.executor import (
    ToolConfirmationRequiredError,
    ToolExecutionError,
    ToolExecutor,
)
from app.tools.registry import ToolRegistry, ToolSpec
from app.tools.tools import register_builtin_tools


@pytest.fixture
def builtin_executor():
    """注册内置工具的执行器。"""
    registry = ToolRegistry()
    register_builtin_tools(registry)
    return ToolExecutor(registry)


class TestNavigationConfirmationRequired:
    """导航工具在驾驶场景下需确认的集成测试。"""

    async def test_highway_scenario_raises_confirmation(self, builtin_executor):
        """Given scenario=highway, LLM returns tool_calls=[navigation], When ToolExecutor processes, Then ToolConfirmationRequiredError is raised."""
        driving = {"scenario": "highway"}

        with pytest.raises(ToolConfirmationRequiredError):
            await builtin_executor.execute(
                "set_navigation",
                {"destination": "北京南站"},
                driving_context=driving,
            )

    async def test_city_scenario_raises_confirmation(self, builtin_executor):
        """Given scenario=city, When execute navigation, Then confirmation required。"""
        driving = {"scenario": "city"}

        with pytest.raises(ToolConfirmationRequiredError):
            await builtin_executor.execute(
                "set_navigation",
                {"destination": "天安门"},
                driving_context=driving,
            )

    async def test_parked_does_not_raise(self, builtin_executor):
        """Given scenario=parked, When execute navigation, Then 正常执行。"""
        driving = {"scenario": "parked"}

        result = await builtin_executor.execute(
            "set_navigation",
            {"destination": "北京南站"},
            driving_context=driving,
        )
        assert result == "导航已设置：北京南站"

    async def test_send_message_no_confirmation_in_highway(self, builtin_executor):
        """Given scenario=highway, send_message has no require_confirmation_when, When execute, Then 正常发送，不抛确认错误。"""
        driving = {"scenario": "highway"}

        result = await builtin_executor.execute(
            "send_message",
            {"recipient": "张三", "message": "路上稍堵，晚十分钟到"},
            driving_context=driving,
        )
        assert "消息已发送给 张三" in result


class TestToolResultInjection:
    """工具执行结果正确返回，可注入 JointDecision 输出。"""

    async def test_send_message_result_returned(self, builtin_executor):
        """Given mock send_message handler returns success, When ToolExecutor executes, Then result is returned and injectable into JointDecision output。"""
        result = await builtin_executor.execute(
            "send_message",
            {"recipient": "李四", "message": "你好"},
        )
        assert result == "消息已发送给 李四"

    async def test_navigation_result_returned(self, builtin_executor):
        """Given parked context, When execute navigation, Then 结果正确返回。"""
        result = await builtin_executor.execute(
            "set_navigation",
            {"destination": "首都机场"},
            driving_context={"scenario": "parked"},
        )
        assert result == "导航已设置：首都机场"

    async def test_custom_tool_result_returned(self):
        """Given ToolRegistry with custom tool returning structured result, When execute, Then result string returned correctly。"""

        async def custom_handler(params: dict) -> str:
            return f"已执行: {params['action']} for {params['target']}"

        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name="custom_action",
                description="自定义操作",
                input_schema={
                    "type": "object",
                    "required": ["action", "target"],
                    "properties": {
                        "action": {"type": "string"},
                        "target": {"type": "string"},
                    },
                },
                handler=custom_handler,
            )
        )
        executor = ToolExecutor(registry)

        result = await executor.execute(
            "custom_action",
            {"action": "remind", "target": "user"},
        )
        assert result == "已执行: remind for user"

    async def test_tool_error_contains_tool_name(self):
        """Given invalid params, When execute, Then error message references tool name。"""

        async def fail_handler(params: dict) -> str:
            msg = "handler crash"
            raise RuntimeError(msg)

        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name="crash_tool",
                description="测试崩溃",
                input_schema={
                    "type": "object",
                    "required": ["input"],
                    "properties": {"input": {"type": "string"}},
                },
                handler=fail_handler,
            )
        )
        executor = ToolExecutor(registry)

        with pytest.raises(ToolExecutionError, match="handler crash"):
            await executor.execute("crash_tool", {"input": "test"})


class TestConfirmationLogicEdgeCases:
    """确认逻辑边界情况。"""

    async def test_no_driving_context_passes(self, builtin_executor):
        """Given 无 driving_context, When execute navigation, Then 正常执行。"""
        result = await builtin_executor.execute(
            "set_navigation", {"destination": "西直门"}
        )
        assert result == "导航已设置：西直门"

    async def test_empty_driving_context_defaults_parked(self, builtin_executor):
        """Given empty driving_context dict, When execute, Then scenario 默认 parked 不抛确认错误。"""
        result = await builtin_executor.execute(
            "set_navigation",
            {"destination": "西直门"},
            driving_context={},
        )
        assert result == "导航已设置：西直门"

    async def test_scenario_unknown_raises_confirmation(self, builtin_executor):
        """Given scenario=unknown driving state, When execute navigation, Then 非 parked 都应抛确认错误。"""
        driving = {"scenario": "mountain"}

        with pytest.raises(ToolConfirmationRequiredError):
            await builtin_executor.execute(
                "set_navigation",
                {"destination": "张家界"},
                driving_context=driving,
            )
