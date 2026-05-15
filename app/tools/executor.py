from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class ToolExecutionError(RuntimeError):
    pass


class ToolExecutor:
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def execute(self, tool_name: str, params: dict[str, Any]) -> str:
        spec = self._registry.get(tool_name)
        if spec is None:
            raise ToolExecutionError(f"Unknown tool: {tool_name}")
        try:
            result = await spec.handler(params)
            return result
        except Exception as e:
            logger.warning("Tool %s failed: %s", tool_name, e)
            raise ToolExecutionError(str(e)) from e
