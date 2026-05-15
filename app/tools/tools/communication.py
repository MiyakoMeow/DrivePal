"""通信工具。"""

from typing import Any

_MAX_MESSAGE_LENGTH = 200


async def send_message(params: dict[str, Any]) -> str:
    """发送消息给联系人。"""
    recipient = params.get("recipient", "")
    message = params.get("message", "")
    if not recipient or not message:
        return "发送失败：缺少收件人或消息内容"
    if len(message) > _MAX_MESSAGE_LENGTH:
        return f"发送失败：消息超过 {_MAX_MESSAGE_LENGTH} 字限制"
    return f"消息已发送给 {recipient}"
