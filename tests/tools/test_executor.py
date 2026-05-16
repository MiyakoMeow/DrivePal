"""工具执行器测试。"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tools.executor import (
    ToolConfirmationRequiredError,
    ToolExecutionError,
    ToolExecutor,
)
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


async def test_builtin_navigation_tool_executes(builtin_executor):
    """Given set_navigation 注册, When execute, Then 返回导航确认。"""
    result = await builtin_executor.execute(
        "set_navigation", {"destination": "北京南站"}
    )
    assert result == "导航已设置：北京南站"


async def test_disabled_tools_not_registered(builtin_executor):
    """Given vehicle enabled=false, When 查注册表, Then set_climate/play_media 不存在。"""
    registry = builtin_executor._registry
    assert registry.get("set_climate") is None
    assert registry.get("play_media") is None
    with pytest.raises(ToolExecutionError, match="Unknown tool"):
        await builtin_executor.execute("set_climate", {"temperature": 22})
    with pytest.raises(ToolExecutionError, match="Unknown tool"):
        await builtin_executor.execute("play_media", {"name": "test"})


async def test_query_memory_returns_results(builtin_executor):
    """Given mock MemoryModule 返回结果, When execute query_memory, Then 返回内容文本。"""
    from app.memory.schemas import SearchResult

    fake_results = [
        SearchResult(
            event={"content": "明天下午三点开会"},
            score=0.9,
            source="faiss",
        ),
    ]
    mock_mm = AsyncMock()
    mock_mm.search.return_value = fake_results

    mock_cfg = MagicMock()
    mock_cfg.memory_query.max_results = 5
    with (
        patch("app.tools.tools.memory_query.get_memory_module", return_value=mock_mm),
        patch("app.tools.tools.memory_query.ToolsConfig.load", return_value=mock_cfg),
    ):
        result = await builtin_executor.execute("query_memory", {"query": "开会"})
    assert "明天下午三点开会" in result
    mock_mm.search.assert_awaited_once_with("开会", top_k=5)


async def test_send_message_max_length_rejected(builtin_executor):
    """Given message 超 200 字, When execute send_message, Then 抛 ToolExecutionError。"""
    with pytest.raises(ToolExecutionError, match="maxLength"):
        await builtin_executor.execute(
            "send_message", {"recipient": "张三", "message": "a" * 201}
        )


async def test_app_error_not_wrapped():
    """handler 抛 AppError 子类时应原样传播，不包装为 ToolExecutionError。"""
    from app.exceptions import AppError

    class CustomError(AppError):
        def __init__(self) -> None:
            super().__init__(code="CUSTOM", message="custom error")

    registry = ToolRegistry()
    spec = ToolSpec(
        name="fail_tool",
        description="test",
        input_schema={},
        handler=AsyncMock(side_effect=CustomError()),
    )
    registry.register(spec)
    executor = ToolExecutor(registry)
    with pytest.raises(CustomError):
        await executor.execute("fail_tool", {})


async def _echo_handler(params: dict) -> str:
    return f"echo: {params}"


def test_tool_spec_require_confirmation_default():
    """ToolSpec 默认 require_confirmation_when 为 None。"""
    spec = ToolSpec(
        name="test",
        description="test",
        input_schema={},
        handler=_echo_handler,
    )
    assert spec.require_confirmation_when is None


def test_tool_spec_require_confirmation_driving():
    """ToolSpec 可设置 require_confirmation_when='driving'。"""
    spec = ToolSpec(
        name="test",
        description="test",
        input_schema={},
        handler=_echo_handler,
        require_confirmation_when="driving",
    )
    assert spec.require_confirmation_when == "driving"


async def _noop_handler(params: dict) -> str:
    return "ok"


async def test_tool_confirmation_required_when_driving():
    """驾驶中执行需确认的工具抛 ToolConfirmationRequiredError。"""
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="test_nav",
            description="test",
            input_schema={},
            handler=_noop_handler,
            require_confirmation_when="driving",
        )
    )
    executor = ToolExecutor(registry)
    driving = {"scenario": "highway"}
    with pytest.raises(ToolConfirmationRequiredError):
        await executor.execute("test_nav", {}, driving_context=driving)


async def test_tool_confirmation_allowed_when_parked():
    """停车时允许执行需确认的工具。"""
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="test_nav",
            description="test",
            input_schema={},
            handler=_noop_handler,
            require_confirmation_when="driving",
        )
    )
    executor = ToolExecutor(registry)
    parked = {"scenario": "parked"}
    result = await executor.execute("test_nav", {}, driving_context=parked)
    assert result == "ok"


async def test_tool_confirmation_no_context():
    """无驾驶上下文时允许执行。"""
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="test_nav",
            description="test",
            input_schema={},
            handler=_noop_handler,
            require_confirmation_when="driving",
        )
    )
    executor = ToolExecutor(registry)
    result = await executor.execute("test_nav", {})
    assert result == "ok"
