"""导航工具。"""

from typing import Any


async def navigate_to(params: dict[str, Any]) -> str:
    """设置导航目的地。"""
    destination = params.get("destination", "")
    if not destination:
        return "导航失败：未指定目的地"
    return f"导航已设置：{destination}"
