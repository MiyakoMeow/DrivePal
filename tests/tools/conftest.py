"""Tools 测试共享 fixtures."""

import pytest

from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry
from app.tools.tools import register_builtin_tools


@pytest.fixture
def builtin_executor():
    """注册内置工具的执行器。"""
    registry = ToolRegistry()
    register_builtin_tools(registry)
    return ToolExecutor(registry)
