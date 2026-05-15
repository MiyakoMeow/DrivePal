"""内置工具集合入口。"""

import logging

from app.tools.config import ToolsConfig
from app.tools.registry import ToolRegistry, ToolSpec
from app.tools.tools.communication import send_message
from app.tools.tools.memory_query import query_memory
from app.tools.tools.navigation import navigate_to
from app.tools.tools.vehicle import play_media, set_climate

logger = logging.getLogger(__name__)


def register_builtin_tools(
    registry: ToolRegistry, cfg: ToolsConfig | None = None
) -> None:
    """注册所有内置工具到给定注册表。cfg 未传时读 tools.toml（缺失则自动生成）。"""
    if cfg is None:
        cfg = ToolsConfig.load()

    if cfg.navigation.enabled:
        registry.register(
            ToolSpec(
                name="set_navigation",
                description="设置导航目的地",
                input_schema={
                    "type": "object",
                    "properties": {
                        "destination": {
                            "type": "string",
                            "description": "目的地名称或地址",
                        },
                    },
                    "required": ["destination"],
                },
                handler=navigate_to,
            )
        )
    if cfg.memory_query.enabled:
        registry.register(
            ToolSpec(
                name="query_memory",
                description="查询过往记忆事件",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索关键词"},
                    },
                    "required": ["query"],
                },
                handler=query_memory,
            )
        )
    if cfg.communication.enabled:
        registry.register(
            ToolSpec(
                name="send_message",
                description="发送消息给联系人",
                input_schema={
                    "type": "object",
                    "properties": {
                        "recipient": {"type": "string"},
                        "message": {
                            "type": "string",
                            "maxLength": cfg.communication.max_message_length,
                        },
                    },
                    "required": ["recipient", "message"],
                },
                handler=send_message,
            )
        )
    if cfg.vehicle.enabled:
        registry.register(
            ToolSpec(
                name="set_climate",
                description="设置车内空调温度",
                input_schema={
                    "type": "object",
                    "properties": {
                        "temperature": {
                            "type": "number",
                            "minimum": cfg.vehicle.temperature_min,
                            "maximum": cfg.vehicle.temperature_max,
                        },
                    },
                    "required": ["temperature"],
                },
                handler=set_climate,
            )
        )
        registry.register(
            ToolSpec(
                name="play_media",
                description="播放音乐或播客",
                input_schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "音乐/播客名称"},
                        "type": {"type": "string", "enum": ["music", "podcast"]},
                    },
                    "required": ["name"],
                },
                handler=play_media,
            )
        )
