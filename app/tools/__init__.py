"""工具模块入口。"""

from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry
from app.tools.tools import register_builtin_tools

_default_registry = ToolRegistry()
register_builtin_tools(_default_registry)

_default_executor: list[ToolExecutor] = []


def get_default_executor() -> ToolExecutor:
    """获取默认工具执行器（单例模式）。"""
    if not _default_executor:
        _default_executor.append(ToolExecutor(_default_registry))
    return _default_executor[0]
