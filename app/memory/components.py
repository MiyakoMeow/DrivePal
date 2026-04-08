"""MemoryStore 可组合组件."""

import asyncio
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from app.memory.schemas import FeedbackData, MemoryEvent, SearchResult
from app.storage.toml_store import TOMLStore

SUMMARY_WEIGHT = 0.8


def forgetting_curve(days_elapsed: int, strength: int) -> float:
    """遗忘曲线衰减函数."""
    if days_elapsed <= 0:
        return 1.0
    if strength <= 0:
        return 0.0
    return math.exp(-days_elapsed / (5 * strength))


class EventStorage:
    """事件 JSON 文件 CRUD + ID 生成."""

    def __init__(self, data_dir: Path) -> None:
        """初始化事件存储."""
        self._store = TOMLStore(data_dir, Path("events.toml"), list)
        self.data_dir = data_dir

    @property
    def store(self) -> TOMLStore:
        """事件存储."""
        return self._store

    def generate_id(self) -> str:
        """生成唯一事件 ID."""
        return f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

    async def read_events(self) -> list[dict]:
        """读取所有事件."""
        return await self._store.read()

    async def write_events(self, events: list[dict]) -> None:
        """覆写全部事件."""
        await self._store.write(events)

    async def append_event(self, event: MemoryEvent) -> str:
        """追加事件并返回 ID."""
        event = event.model_copy(deep=True)
        event.id = self.generate_id()
        event.created_at = datetime.now(timezone.utc).isoformat()
        await self._store.append(event.model_dump())
        return event.id

    async def append_raw(self, event: dict) -> None:
        """追加原始事件字典."""
        await self._store.append(event)


class KeywordSearch:
    """关键词大小写不敏感搜索."""

    def search(
        self, query: str, events: list[dict], top_k: int = 10
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


_strategy_locks: dict[str, asyncio.Lock] = {}
_strategy_locks_lock = asyncio.Lock()


def clear_strategy_locks() -> None:
    """清除全局策略锁缓存（仅用于测试清理）."""
    _strategy_locks.clear()


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
            key = str(self.data_dir.resolve())
            if key not in _strategy_locks:
                _strategy_locks[key] = asyncio.Lock()
            return _strategy_locks[key]

    async def _write_feedback(self, feedback: FeedbackData) -> None:
        """写入反馈记录."""
        await self._feedback_store.append(feedback.model_dump())

    async def _update_strategy(
        self, event_type: str, action: Literal["accept", "ignore"]
    ) -> None:
        """更新策略权重."""
        strategies = await self._strategies_store.read()

        if "reminder_weights" not in strategies:
            strategies["reminder_weights"] = {}

        if action == "accept":
            strategies["reminder_weights"][event_type] = min(
                strategies["reminder_weights"].get(event_type, 0.5) + 0.1, 1.0
            )
        elif action == "ignore":
            strategies["reminder_weights"][event_type] = max(
                strategies["reminder_weights"].get(event_type, 0.5) - 0.1, 0.1
            )

        await self._strategies_store.write(strategies)

    async def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        """记录反馈并更新策略权重."""
        feedback.event_id = event_id
        feedback.timestamp = datetime.now(timezone.utc).isoformat()
        if feedback.action is None:
            raise ValueError("action is required")
        lock = await self._get_lock()
        async with lock:
            await self._write_feedback(feedback)
            await self._update_strategy(feedback.type, feedback.action)


class SimpleInteractionWriter:
    """简单交互写入（创建 MemoryEvent 写入 EventStorage）."""

    def __init__(self, storage: EventStorage) -> None:
        """初始化交互写入器."""
        self._storage = storage

    async def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str:
        """写入交互记录."""
        event = MemoryEvent(
            content=query,
            type=event_type,
            description=response,
        )
        return await self._storage.append_event(event)
