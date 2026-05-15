"""工具注册表。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

ToolHandler = Callable[[dict[str, Any]], Awaitable[str]]


@dataclass(frozen=True)
class ToolSpec:
    """工具规格说明。"""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler


class ToolRegistry:
    """工具注册表，管理工具规格的增删查改。"""

    def __init__(self) -> None:
        """初始化空工具注册表。"""
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        """注册工具，同名工具重复注册将抛出异常。"""
        if spec.name in self._tools:
            msg = f"Tool {spec.name} already registered"
            raise ValueError(msg)
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        """按名称查找工具。"""
        return self._tools.get(name)

    def list_tools(self) -> list[ToolSpec]:
        """列出所有已注册工具。"""
        return list(self._tools.values())

    def to_llm_description(self) -> str:
        """生成供 LLM 理解的工具列表描述文本。"""
        return "\n".join(f"- {t.name}: {t.description}" for t in self._tools.values())
