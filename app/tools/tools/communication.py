"""通信工具。"""

from typing import Any

from app.tools.config import ToolsConfig


async def send_message(params: dict[str, Any]) -> str:
    """发送消息给联系人。"""
    max_len = ToolsConfig.load().communication.max_message_length
    recipient = params.get("recipient", "")
    message = params.get("message", "")
    if not recipient or not message:
        return "发送失败：缺少收件人或消息内容"
    if len(message) > max_len:
        return f"发送失败：消息超过 {max_len} 字限制"
    return f"消息已发送给 {recipient}"
