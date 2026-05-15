"""内置工具集合入口。"""

import logging
import tomllib
from pathlib import Path

from app.tools.registry import ToolRegistry, ToolSpec
from app.tools.tools.communication import send_message
from app.tools.tools.memory_query import query_memory
from app.tools.tools.navigation import navigate_to
from app.tools.tools.vehicle import play_media, set_climate

logger = logging.getLogger(__name__)


def _load_tools_config() -> dict:
    """从 tools.toml 读取工具配置，失败返回空字典。"""
    try:
        with Path("config/tools.toml").open("rb") as f:
            data = tomllib.load(f)
        return data.get("tools", {})
    except OSError, tomllib.TOMLDecodeError:
        logger.warning("Failed to read config/tools.toml")
        return {}


def register_builtin_tools(registry: ToolRegistry) -> None:
    """注册所有内置工具到给定注册表。"""
    cfg = _load_tools_config()
    comm_cfg = cfg.get("communication", {})
    max_msg_len = comm_cfg.get("max_message_length", 200)
    vehicle_cfg = cfg.get("vehicle", {})
    temp_min = vehicle_cfg.get("temperature_min", 16)
    temp_max = vehicle_cfg.get("temperature_max", 32)

    def is_enabled(name: str) -> bool:
        return cfg.get(name, {}).get("enabled", True)

    if is_enabled("navigation"):
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
    if is_enabled("memory_query"):
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
    if is_enabled("communication"):
        registry.register(
            ToolSpec(
                name="send_message",
                description="发送消息给联系人",
                input_schema={
                    "type": "object",
                    "properties": {
                        "recipient": {"type": "string"},
                        "message": {"type": "string", "maxLength": max_msg_len},
                    },
                    "required": ["recipient", "message"],
                },
                handler=send_message,
            )
        )
    if is_enabled("vehicle"):
        registry.register(
            ToolSpec(
                name="set_climate",
                description="设置车内空调温度",
                input_schema={
                    "type": "object",
                    "properties": {
                        "temperature": {
                            "type": "number",
                            "minimum": temp_min,
                            "maximum": temp_max,
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
