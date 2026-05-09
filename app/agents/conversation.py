"""会话管理——多轮对话支持."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass
class ConversationTurn:
    turn_id: int
    query: str
    decision_snapshot: dict
    response_summary: str = ""
    timestamp: str = ""


class ConversationManager:
    """管理会话生命周期和 turn 历史。纯内存，服务重启丢失。"""

    def __init__(self, ttl_minutes: int = 30) -> None:
        self._sessions: dict[str, dict] = {}
        self._ttl = ttl_minutes

    def create(self, user_id: str) -> str:
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
        if len(session["turns"]) > 10:
            session["turns"] = session["turns"][-10:]
        session["last_activity"] = datetime.now(UTC).isoformat()

    def get_history(self, session_id: str) -> list[ConversationTurn]:
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
        except (ValueError, TypeError):
            pass
        return list(session["turns"])

    def close(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def cleanup_expired(self) -> None:
        now = datetime.now(UTC)
        expired = []
        for sid, session in list(self._sessions.items()):
            try:
                last = datetime.fromisoformat(session["last_activity"])
                if last.tzinfo is None:
                    last = last.replace(tzinfo=UTC)
                if now - last > timedelta(minutes=self._ttl):
                    expired.append(sid)
            except (ValueError, TypeError):
                expired.append(sid)
        for sid in expired:
            del self._sessions[sid]


# 模块级单例——供 workflow 和 mutation 共享
_conversation_manager = ConversationManager()
