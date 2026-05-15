"""工具模块入口。"""

from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry
from app.tools.tools import register_builtin_tools

_default_registry = ToolRegistry()
register_builtin_tools(_default_registry)


def get_default_executor() -> ToolExecutor:
    """获取默认工具执行器（单例模式）。"""
    return ToolExecutor(_default_registry)
