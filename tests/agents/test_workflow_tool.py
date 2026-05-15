"""工具异常在工作流中的传播测试。"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.execution_agent import ExecutionAgent
from app.exceptions import AppError
from app.tools.executor import ToolExecutionError, ToolExecutor
from app.tools.registry import ToolRegistry, ToolSpec


class TestToolExceptionInWorkflow:
    """工具异常在 _handle_tool_calls 中的处理。"""

    async def test_tool_execution_error_does_not_interrupt(self):
        """ToolExecutionError 追加错误文本，不中断后续工具。"""
        registry = ToolRegistry()
        spec_fail = ToolSpec(
            name="fail_tool",
            description="test",
            input_schema={},
            handler=AsyncMock(side_effect=ToolExecutionError("boom")),
        )
        spec_ok = ToolSpec(
            name="ok_tool",
            description="test",
            input_schema={},
            handler=AsyncMock(return_value="ok"),
        )
        registry.register(spec_fail)
        registry.register(spec_ok)

        with patch(
            "app.agents.execution_agent.get_default_executor",
            return_value=ToolExecutor(registry),
        ):
            ea = ExecutionAgent.__new__(ExecutionAgent)
            state: dict = {}
            await ea._handle_tool_calls(
                {
                    "tool_calls": [
                        {"tool": "fail_tool", "params": {}},
                        {"tool": "ok_tool", "params": {}},
                    ]
                },
                state,
            )

        spec_ok.handler.assert_awaited_once()

    async def test_workflow_error_interrupts(self):
        """WorkflowError 应中断工具执行循环。"""
        from app.agents.types import WorkflowError

        registry = ToolRegistry()
        spec = ToolSpec(
            name="wf_fail",
            description="test",
            input_schema={},
            handler=AsyncMock(side_effect=WorkflowError()),
        )
        registry.register(spec)

        with patch(
            "app.agents.execution_agent.get_default_executor",
            return_value=ToolExecutor(registry),
        ):
            ea = ExecutionAgent.__new__(ExecutionAgent)
            with pytest.raises(WorkflowError):
                await ea._handle_tool_calls(
                    {"tool_calls": [{"tool": "wf_fail", "params": {}}]},
                    {},
                )

    async def test_app_error_interrupts(self):
        """非 WorkflowError 的 AppError 也应中断。"""

        class CustomAppError(AppError):
            def __init__(self) -> None:
                super().__init__(code="CUSTOM", message="custom")

        registry = ToolRegistry()
        spec = ToolSpec(
            name="app_fail",
            description="test",
            input_schema={},
            handler=AsyncMock(side_effect=CustomAppError()),
        )
        registry.register(spec)

        with patch(
            "app.agents.execution_agent.get_default_executor",
            return_value=ToolExecutor(registry),
        ):
            ea = ExecutionAgent.__new__(ExecutionAgent)
            with pytest.raises(CustomAppError):
                await ea._handle_tool_calls(
                    {"tool_calls": [{"tool": "app_fail", "params": {}}]},
                    {},
                )
