"""检索当前上下文相关的记忆。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.memory.memory import MemoryModule

logger = logging.getLogger(__name__)


class MemoryScanner:
    """根据驾驶上下文检索相关记忆。"""

    def __init__(self, memory_module: MemoryModule, user_id: str = "default") -> None:
        """初始化 MemoryScanner。

        Args:
            memory_module: 统一记忆管理模块。
            user_id: 目标用户 ID。

        """
        self._memory = memory_module
        self._user_id = user_id

    async def scan_by_context(self, ctx: dict, top_k: int = 10) -> list[dict]:
        """根据当前上下文检索相关记忆。"""
        scenario = str(ctx.get("scenario", ""))
        location = ctx.get("spatial", {}).get("current_location", {})
        query_parts: list[str] = [scenario]
        if location:
            query_parts.append(
                f"位置 {location.get('latitude')},{location.get('longitude')}"
            )
        query = " ".join(query_parts)
        try:
            results = await self._memory.search(
                query, top_k=top_k, user_id=self._user_id
            )
            return [r.to_public() for r in results]
        except (OSError, RuntimeError, ValueError, TypeError) as e:
            logger.warning("MemoryScanner search failed: %s", e)
            return []

    async def scan_by_scenario_change(
        self, old_scenario: str, new_scenario: str, top_k: int = 5
    ) -> list[dict]:
        """场景切换时检索相关记忆。"""
        query = f"从{old_scenario}切换到{new_scenario}"
        try:
            results = await self._memory.search(
                query, top_k=top_k, user_id=self._user_id
            )
            return [r.to_public() for r in results]
        except (OSError, RuntimeError, ValueError, TypeError) as e:
            logger.warning("MemoryScanner scenario search failed: %s", e)
            return []
