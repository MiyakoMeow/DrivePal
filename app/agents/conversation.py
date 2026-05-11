"""会话管理——多轮对话支持.

注意事项：ConversationManager 为纯同步类，旨在 asyncio 单线程事件循环中运行。
方法无 await 点，故在协程间原子执行。若将来迁移至多线程事件循环，需加 asyncio.Lock。
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)

_MAX_TURNS = 10


@dataclass
class ConversationTurn:
    """单轮对话记录."""

    turn_id: int
    query: str
    decision_snapshot: dict
    response_summary: str = ""
    timestamp: str = ""


class ConversationManager:
    """管理会话生命周期和 turn 历史。纯内存，服务重启丢失。"""

    def __init__(self, ttl_minutes: int = 30) -> None:
        """初始化会话管理器。

        Args:
            ttl_minutes: 会话过期时间（分钟），默认 30。

        """
        self._sessions: dict[str, dict] = {}
        self._ttl = ttl_minutes

    def create(self, user_id: str) -> str:
        """创建新会话并返回会话 ID。"""
        sid = f"s_{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC).isoformat()
        self._sessions[sid] = {
            "session_id": sid,
            "user_id": user_id,
            "created_at": now,
            "last_activity": now,
            "turns": [],
        }
        return sid

    def _exists(self, session_id: str) -> bool:
        return session_id in self._sessions

    def add_turn(
        self,
        session_id: str,
        query: str,
        decision_snapshot: dict,
        response_summary: str = "",
    ) -> None:
        """追加一轮对话。会话不存在则静默忽略。"""
        if not self._exists(session_id):
            return
        session = self._sessions[session_id]
        turn = ConversationTurn(
            turn_id=len(session["turns"]) + 1,
            query=query,
            decision_snapshot=decision_snapshot,
            response_summary=response_summary,
            timestamp=datetime.now(UTC).isoformat(),
        )
        session["turns"].append(turn)
        if len(session["turns"]) > _MAX_TURNS:
            session["turns"] = session["turns"][-_MAX_TURNS:]
        session["last_activity"] = datetime.now(UTC).isoformat()

    def get_history(self, session_id: str) -> list[ConversationTurn]:
        """获取会话的对话历史，不存在或已过期返回空列表。"""
        if not self._exists(session_id):
            return []
        session = self._sessions[session_id]
        # 惰性检查过期
        try:
            last = datetime.fromisoformat(session["last_activity"])
            if last.tzinfo is None:
                last = last.replace(tzinfo=UTC)
            if datetime.now(UTC) - last > timedelta(minutes=self._ttl):
                del self._sessions[session_id]
                return []
        except ValueError, TypeError:
            logger.debug(
                "Cannot parse last_activity for session %s, treating as valid",
                session_id,
            )
        return list(session["turns"])

    def close(self, session_id: str, user_id: str | None = None) -> bool:
        """关闭指定会话。返回是否实际关闭。"""
        session = self._sessions.get(session_id)
        if session is None:
            return False
        if user_id is not None and session["user_id"] != user_id:
            return False
        del self._sessions[session_id]
        return True

    def cleanup_expired(self) -> None:
        """清理所有超时未活动的会话。"""
        now = datetime.now(UTC)
        expired = []
        for sid, session in list(self._sessions.items()):
            try:
                last = datetime.fromisoformat(session["last_activity"])
                if last.tzinfo is None:
                    last = last.replace(tzinfo=UTC)
                if now - last > timedelta(minutes=self._ttl):
                    expired.append(sid)
            except ValueError, TypeError:
                expired.append(sid)
        for sid in expired:
            del self._sessions[sid]


# 模块级单例——供 workflow 和 mutation 共享
_conversation_manager = ConversationManager()
