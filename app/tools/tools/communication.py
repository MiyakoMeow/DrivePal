from typing import Any


async def send_message(params: dict[str, Any]) -> str:
    recipient = params.get("recipient", "")
    message = params.get("message", "")
    if not recipient or not message:
        return "发送失败：缺少收件人或消息内容"
    return f"消息已发送给 {recipient}"
