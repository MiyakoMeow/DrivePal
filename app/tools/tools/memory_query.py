from typing import Any


async def query_memory(params: dict[str, Any]) -> str:
    query = params.get("query", "")
    if not query:
        return "查询失败：未指定查询内容"
    try:
        from app.memory.singleton import get_memory_module

        mm = get_memory_module()
        results = await mm.search(query, top_k=3)
        if not results:
            return f"未找到与'{query}'相关的记忆"
        texts = [r.event.get("content", "") for r in results if r.event]
        return "\n".join(texts[:3])
    except Exception:
        return "记忆查询失败"
