"""工具模块测试共享夹具——统一内置工具执行器实例化，避免各测试文件重复注册工具造成状态污染。"""

import pytest

from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry
from app.tools.tools import register_builtin_tools


@pytest.fixture
def builtin_executor():
    """提供已注册内置工具的执行器实例。每个测试获得独立实例，避免工具注册状态跨测试泄漏。"""
    registry = ToolRegistry()
    register_builtin_tools(registry)
    return ToolExecutor(registry)
