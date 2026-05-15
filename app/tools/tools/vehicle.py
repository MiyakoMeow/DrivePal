"""车控工具。"""

from typing import Any


async def set_climate(_params: dict[str, Any]) -> str:
    """设置车内空调温度。"""
    return "车控功能尚未接入"


async def play_media(_params: dict[str, Any]) -> str:
    """播放音乐或播客。"""
    return "媒体功能尚未接入"
