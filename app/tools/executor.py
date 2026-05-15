"""工具执行器。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.tools.registry import ToolRegistry, ToolSpec

logger = logging.getLogger(__name__)


class ToolExecutionError(RuntimeError):
    """工具执行异常。"""


class ToolExecutor:
    """工具执行器，按名称分发调用已注册工具。"""

    def __init__(self, registry: ToolRegistry) -> None:
        """注入已注册工具列表。"""
        self._registry = registry

    def _validate_params(
        self, tool_name: str, spec: ToolSpec, params: dict[str, Any]
    ) -> None:
        """校验参数是否符合 input_schema（JSON Schema）。"""
        schema = spec.input_schema or {}
        required = schema.get("required", [])
        properties = schema.get("properties", {})

        missing = [k for k in required if k not in params]
        if missing:
            msg = f"Tool {tool_name}: missing required params: {missing}"
            raise ToolExecutionError(msg)

        for key, value in params.items():
            prop = properties.get(key)
            if prop is None:
                continue
            if "type" in prop:
                type_map = {
                    "string": str,
                    "number": (int, float),
                    "integer": int,
                    "boolean": bool,
                }
                expected = type_map.get(prop["type"])
                if expected is not None and not isinstance(value, expected):
                    msg = f"Tool {tool_name}: param '{key}' expected {prop['type']}, got {type(value).__name__}"
                    raise ToolExecutionError(msg)

    async def execute(self, tool_name: str, params: dict[str, Any]) -> str:
        """按名称执行工具，返回执行结果字符串。"""
        spec = self._registry.get(tool_name)
        if spec is None:
            msg = f"Unknown tool: {tool_name}"
            raise ToolExecutionError(msg)
        self._validate_params(tool_name, spec, params)
        try:
            result = await spec.handler(params)
        except Exception as e:
            logger.warning("Tool %s failed: %s", tool_name, e)
            raise ToolExecutionError(str(e)) from e
        else:
            return result
