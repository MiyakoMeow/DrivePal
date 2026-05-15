"""工具执行器测试。"""

from unittest.mock import AsyncMock

import pytest

from app.tools.executor import ToolExecutionError, ToolExecutor
from app.tools.registry import ToolRegistry, ToolSpec


@pytest.fixture
def registry():
    reg = ToolRegistry()
    reg.register(
        ToolSpec(
            name="test_tool",
            description="Test tool",
            input_schema={
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string", "maxLength": 10},
                    "count": {"type": "integer", "minimum": 1, "maximum": 100},
                    "mode": {"type": "string", "enum": ["fast", "slow"]},
                },
            },
            handler=AsyncMock(return_value="ok"),
        )
    )
    return reg


@pytest.fixture
def executor(registry):
    return ToolExecutor(registry)


async def test_unknown_tool_raises_error(executor):
    """Given 注册表中无该工具, When execute, Then raise ToolExecutionError。"""
    with pytest.raises(ToolExecutionError, match="Unknown tool"):
        await executor.execute("no_such_tool", {})


async def test_missing_required_param_raises_error(executor):
    """Given 缺 required 字段, When execute, Then raise ToolExecutionError。"""
    with pytest.raises(ToolExecutionError, match="missing required"):
        await executor.execute("test_tool", {})


async def test_type_mismatch_raises_error(executor):
    """Given int 字段传 str, When execute, Then raise ToolExecutionError。"""
    with pytest.raises(ToolExecutionError, match="expected integer"):
        await executor.execute("test_tool", {"name": "a", "count": "not_int"})


async def test_minimum_violation_raises_error(executor):
    """Given value < minimum, When execute, Then raise ToolExecutionError。"""
    with pytest.raises(ToolExecutionError, match="minimum"):
        await executor.execute("test_tool", {"name": "a", "count": 0})


async def test_max_length_violation_raises_error(executor):
    """Given len(str) > maxLength, When execute, Then raise ToolExecutionError。"""
    with pytest.raises(ToolExecutionError, match="maxLength"):
        await executor.execute("test_tool", {"name": "a" * 11})


async def test_enum_violation_raises_error(executor):
    """Given value not in enum, When execute, Then raise ToolExecutionError。"""
    with pytest.raises(ToolExecutionError, match="must be one of"):
        await executor.execute("test_tool", {"name": "a", "mode": "invalid"})


async def test_handler_exception_chained(registry):
    """Given handler 抛 RuntimeError, When execute, Then raise ToolExecutionError 且 chain。"""
    registry._tools["test_tool"] = ToolSpec(
        name="test_tool",
        description="Test tool",
        input_schema={
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}},
        },
        handler=AsyncMock(side_effect=RuntimeError("boom")),
    )
    executor = ToolExecutor(registry)
    with pytest.raises(ToolExecutionError) as exc_info:
        await executor.execute("test_tool", {"name": "a"})
    assert exc_info.value.__cause__ is not None
    assert isinstance(exc_info.value.__cause__, RuntimeError)


async def test_valid_execution_returns_result(executor):
    """Given 有效参数, When execute, Then 返回 handler 结果。"""
    result = await executor.execute("test_tool", {"name": "valid"})
    assert result == "ok"
