"""记忆查询工具。"""

import tomllib
from pathlib import Path
from typing import Any

from app.memory.singleton import get_memory_module

_TOP_K = 5


def _load_max_results() -> int:
    """从 tools.toml 读取 max_results，失败返回默认值。"""
    try:
        with Path("config/tools.toml").open("rb") as f:
            data = tomllib.load(f)
        return data.get("tools", {}).get("memory_query", {}).get("max_results", _TOP_K)
    except OSError, tomllib.TOMLDecodeError:
        return _TOP_K


async def query_memory(params: dict[str, Any]) -> str:
    """查询过往记忆事件。"""
    query = params.get("query", "")
    if not query:
        return "查询失败：未指定查询内容"
    try:
        mm = get_memory_module()
        top_k = _load_max_results()
        results = await mm.search(query, top_k=top_k)
        if not results:
            return f"未找到与'{query}'相关的记忆"
        texts = [r.event.get("content", "") for r in results if r.event]
        return "\n".join(texts[:top_k])
    except Exception:
        return "记忆查询失败"
