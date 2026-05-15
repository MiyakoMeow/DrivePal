"""通信工具。"""

import logging
import tomllib
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_MAX_LENGTH = 200


def _load_message_max_length() -> int:
    """从 tools.toml 读取 max_message_length，失败返回默认值。"""
    try:
        with Path("config/tools.toml").open("rb") as f:
            data = tomllib.load(f)
        return (
            data.get("tools", {})
            .get("communication", {})
            .get("max_message_length", _DEFAULT_MAX_LENGTH)
        )
    except OSError, tomllib.TOMLDecodeError:
        logger.warning(
            "Failed to read tools.toml max_message_length, using default %s",
            _DEFAULT_MAX_LENGTH,
        )
        return _DEFAULT_MAX_LENGTH


async def send_message(params: dict[str, Any]) -> str:
    """发送消息给联系人。"""
    max_len = _load_message_max_length()
    recipient = params.get("recipient", "")
    message = params.get("message", "")
    if not recipient or not message:
        return "发送失败：缺少收件人或消息内容"
    if len(message) > max_len:
        return f"发送失败：消息超过 {max_len} 字限制"
    return f"消息已发送给 {recipient}"
