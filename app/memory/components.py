"""MemoryStore 可组合组件."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from app.memory.interfaces import FeedbackHandler

from app.memory.schemas import (
    FeedbackData,
    SearchResult,
)
from app.storage.toml_store import TOMLStore

SUMMARY_WEIGHT = 0.8


class KeywordSearch:
    """关键词大小写不敏感搜索."""

    def search(
        self,
        query: str,
        events: list[dict],
        top_k: int = 10,
    ) -> list[SearchResult]:
        """关键词搜索事件."""
        query_lower = query.lower()
        matched = [
            e
            for e in events
            if query_lower in e.get("content", "").lower()
            or query_lower in e.get("description", "").lower()
        ]
        return [SearchResult(event=e) for e in matched[:top_k]]


class ActionRequiredError(ValueError):
    """action 字段为必需的异常."""

    MSG = "action is required"

    def __init__(self) -> None:
        """初始化异常,使用类常量消息."""
        super().__init__(self.MSG)


_strategy_locks: dict[str, asyncio.Lock] = {}
_strategy_locks_lock = asyncio.Lock()


class FeedbackManager:
    """反馈更新 + 策略权重管理."""

    def __init__(self, data_dir: Path) -> None:
        """初始化反馈管理器."""
        self._strategies_store = TOMLStore(data_dir, Path("strategies.toml"), dict)
        self._feedback_store = TOMLStore(data_dir, Path("feedback.toml"), list)
        self.data_dir = data_dir

    @property
    def strategies_store(self) -> TOMLStore:
        """策略存储."""
        return self._strategies_store

    async def _get_lock(self) -> asyncio.Lock:
        async with _strategy_locks_lock:
            if str(self.data_dir) not in _strategy_locks:
                _strategy_locks[str(self.data_dir)] = asyncio.Lock()
            lock = _strategy_locks[str(self.data_dir)]
        return lock  # noqa: RET504 — return 故意移出 async with 块

    async def _write_feedback(self, feedback: FeedbackData) -> None:
        """写入反馈记录."""
        await self._feedback_store.append(feedback.model_dump())

    async def _update_strategy(
        self,
        event_type: str,
        action: Literal["accept", "ignore"],
    ) -> None:
        """更新策略权重."""
        strategies = await self._strategies_store.read()

        if "reminder_weights" not in strategies:
            strategies["reminder_weights"] = {}

        if action == "accept":
            strategies["reminder_weights"][event_type] = min(
                strategies["reminder_weights"].get(event_type, 0.5) + 0.1,
                1.0,
            )
        elif action == "ignore":
            strategies["reminder_weights"][event_type] = max(
                strategies["reminder_weights"].get(event_type, 0.5) - 0.1,
                0.1,
            )

        await self._strategies_store.write(strategies)

    async def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        """记录反馈并更新策略权重."""
        feedback.event_id = event_id
        feedback.timestamp = datetime.now(UTC).isoformat()
        if feedback.action is None:
            raise ActionRequiredError
        lock = await self._get_lock()
        async with lock:
            await self._write_feedback(feedback)
            await self._update_strategy(feedback.type, feedback.action)
