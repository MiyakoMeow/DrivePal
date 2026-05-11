"""测试 ConversationManager."""

import pytest

from app.agents.conversation import ConversationManager


class TestConversationManager:
    async def test_create_and_add_turn(self):
        """Given 新会话, When 追加 turn, Then 轮次数正确."""
        cm = ConversationManager()
        sid = cm.create("user1")
        cm.add_turn(
            sid, "提醒我到公司", {"should_remind": True, "type": "travel"}, "已设置提醒"
        )
        history = cm.get_history(sid)
        assert len(history) == 1
        assert history[0].query == "提醒我到公司"

    async def test_history_limited_to_10(self):
        """Given 追加 12 轮, When get_history, Then 仅返回最近 10."""
        cm = ConversationManager()
        sid = cm.create("user1")
        for i in range(12):
            cm.add_turn(sid, f"query{i}", {"type": "test"}, f"response{i}")
        assert len(cm.get_history(sid)) == 10

    async def test_close_removes_session(self):
        """Given 活跃会话, When close, Then 会话不存在."""
        cm = ConversationManager()
        sid = cm.create("user1")
        cm.close(sid)
        assert cm.get_history(sid) == []

    async def test_cleanup_expired_sessions(self):
        """Given 超时会话, When cleanup, Then 移除."""
        cm = ConversationManager(ttl_minutes=1)
        sid = cm.create("user1")
        cm._sessions[sid]["last_activity"] = "2000-01-01T00:00:00"
        cm.cleanup_expired()
        assert cm.get_history(sid) == []

    async def test_unknown_session_returns_empty(self):
        """Given 不存在的 session_id, When get_history, Then 返回空列表."""
        cm = ConversationManager()
        assert cm.get_history("nonexistent") == []

    async def test_close_session_checks_user(self):
        """Given 用户 A 的会话, When 用户 B 关闭, Then 拒绝; 用户 A 关闭, Then 成功."""
        cm = ConversationManager()
        sid = cm.create("user_a")
        assert cm.close(sid, user_id="user_b") is False
        assert cm.close(sid, user_id="user_a") is True

    async def test_close_session_nonexistent(self):
        """Given 不存在的 session_id, When close, Then 返回 False."""
        cm = ConversationManager()
        assert cm.close("nonexistent") is False
