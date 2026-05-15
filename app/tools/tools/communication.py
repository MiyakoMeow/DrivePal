"""通信工具。"""

from typing import Any

from app.tools.config import ToolsConfig

# 模块级缓存（list 容器避免 PLW0603 global 警告）
# 首次成功加载后避免重复读文件；不在 except 中回退，允许瞬态错误后自动恢复
_max_msg_len: list[int | None] = [None]


async def send_message(params: dict[str, Any]) -> str:
    """发送消息给联系人。"""
    if _max_msg_len[0] is None:
        _max_msg_len[0] = ToolsConfig.load().communication.max_message_length
    max_len = _max_msg_len[0]
    recipient = params.get("recipient", "")
    message = params.get("message", "")
    if not recipient or not message:
        return "发送失败：缺少收件人或消息内容"
    if len(message) > max_len:
        return f"发送失败：消息超过 {max_len} 字限制"
    return f"消息已发送给 {recipient}"
