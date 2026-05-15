"""记忆查询工具。"""

import logging
from typing import Any

from app.memory.singleton import get_memory_module
from app.tools.config import ToolsConfig

logger = logging.getLogger(__name__)

# 模块级缓存，与 communication.py 缓存策略一致
_max_results: list[int | None] = [None]


async def query_memory(params: dict[str, Any]) -> str:
    """查询过往记忆事件。"""
    query = params.get("query", "")
    if not query:
        return "查询失败：未指定查询内容"
    try:
        mm = get_memory_module()
        if _max_results[0] is None:
            _max_results[0] = ToolsConfig.load().memory_query.max_results
        top_k = _max_results[0]
        results = await mm.search(query, top_k=top_k)
        if not results:
            return f"未找到与'{query}'相关的记忆"
        texts = [r.event.get("content", "") for r in results if r.event]
        return "\n".join(texts[:top_k])
    except Exception:
        logger.exception("Memory query failed for query=%s", query)
        return "记忆查询失败"
