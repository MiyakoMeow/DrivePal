"""工具执行器集成测试——验证驾驶场景下导航确认逻辑，及工具结果正确返回。"""

from unittest.mock import patch

import pytest

from app.tools.executor import (
    ToolConfirmationRequiredError,
    ToolExecutionError,
    ToolExecutor,
)
from app.tools.registry import ToolRegistry, ToolSpec


class TestNavigationConfirmationRequired:
    """导航工具在驾驶场景下需二次确认，防止分散驾驶员注意力。"""

    async def test_highway_scenario_raises_confirmation(self, builtin_executor):
        """高速场景执行导航必须抛确认错误，因 require_confirmation_when 约束。"""
        driving = {"scenario": "highway"}

        with pytest.raises(ToolConfirmationRequiredError):
            await builtin_executor.execute(
                "set_navigation",
                {"destination": "北京南站"},
                driving_context=driving,
            )

    async def test_city_scenario_raises_confirmation(self, builtin_executor):
        """城市道路同样需确认，驾驶中任何非停车场景均应拦截。"""
        driving = {"scenario": "city"}

        with pytest.raises(ToolConfirmationRequiredError):
            await builtin_executor.execute(
                "set_navigation",
                {"destination": "天安门"},
                driving_context=driving,
            )

    async def test_parked_does_not_raise(self, builtin_executor):
        """停车场景无需确认，允许直接执行导航。"""
        driving = {"scenario": "parked"}

        result = await builtin_executor.execute(
            "set_navigation",
            {"destination": "北京南站"},
            driving_context=driving,
        )
        assert result == "导航已设置：北京南站"

    async def test_send_message_no_confirmation_in_highway(self, builtin_executor):
        """send_message 无 require_confirmation_when，即使高速也应放行，确保非危险工具不受影响。"""
        driving = {"scenario": "highway"}

        result = await builtin_executor.execute(
            "send_message",
            {"recipient": "张三", "message": "路上稍堵，晚十分钟到"},
            driving_context=driving,
        )
        assert "消息已发送给 张三" in result


class TestToolResultReturn:
    """工具执行结果返回验证——确保 ToolExecutor 正确透传 handler 返回值，供 JointDecision 注入。"""

    async def test_send_message_result_returned(self, builtin_executor):
        """send_message 返回格式化文本，验证结果字符串包含收件人姓名。"""
        result = await builtin_executor.execute(
            "send_message",
            {"recipient": "李四", "message": "你好"},
        )
        assert result == "消息已发送给 李四"

    async def test_navigation_result_returned(self, builtin_executor):
        """停车场景导航返回正确结果字符串。"""
        result = await builtin_executor.execute(
            "set_navigation",
            {"destination": "首都机场"},
            driving_context={"scenario": "parked"},
        )
        assert result == "导航已设置：首都机场"

    async def test_custom_tool_result_returned(self):
        """自定义工具透传 handler 返回值，验证执行器不篡改结果字符串。"""

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
        """handler 抛 RuntimeError 时执行器包装为 ToolExecutionError，保留原始消息供诊断。"""

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
    """确认逻辑边界情况——无上下文、空上下文、非标准场景的处理。"""

    async def test_no_driving_context_passes(self, builtin_executor):
        """无 driving_context 时放行导航，因无法判断场景，不过度限制。"""
        result = await builtin_executor.execute(
            "set_navigation", {"destination": "西直门"}
        )
        assert result == "导航已设置：西直门"

    async def test_empty_driving_context_defaults_parked(self, builtin_executor):
        """空 driving_context 默认视为停车，导航直接执行不抛确认错误。"""
        result = await builtin_executor.execute(
            "set_navigation",
            {"destination": "西直门"},
            driving_context={},
        )
        assert result == "导航已设置：西直门"

    async def test_non_parked_scenario_raises_confirmation(self, builtin_executor):
        """mountain 非停车场景仍抛确认错误，确认规则覆盖所有非 parked 值。"""
        driving = {"scenario": "mountain"}

        with pytest.raises(ToolConfirmationRequiredError):
            await builtin_executor.execute(
                "set_navigation",
                {"destination": "张家界"},
                driving_context=driving,
            )
