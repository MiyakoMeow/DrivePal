"""通信工具。"""

import logging
from typing import Any

from app.tools.config import ToolsConfig

logger = logging.getLogger(__name__)


async def send_message(params: dict[str, Any]) -> str:
    """发送消息给联系人。"""
    cfg = ToolsConfig.load()
    max_len = cfg.communication.max_message_length
    recipient = params.get("recipient", "")
    message = params.get("message", "")
    if not recipient or not message:
        return "发送失败：缺少收件人或消息内容"
    if len(message) > max_len:
        return f"发送失败：消息超过 {max_len} 字限制"
    return f"消息已发送给 {recipient}"
