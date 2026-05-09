"""统一记忆管理接口，Facade 模式 + 工厂注册表."""

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from app.memory.memory_bank import MemoryBankStore
from app.memory.types import MemoryMode
from app.models.chat import get_chat_model
from app.models.embedding import get_cached_embedding_model


class UnknownModeError(ValueError):
    """未知记忆模式异常."""

    MSG = "Unknown mode: {mode}"

    def __init__(self, mode: MemoryMode) -> None:
        super().__init__(self.MSG.format(mode=mode))


if TYPE_CHECKING:
    from pathlib import Path

    from app.memory.interfaces import MemoryStore
    from app.memory.schemas import (
        FeedbackData,
        InteractionResult,
        MemoryEvent,
        SearchResult,
    )
    from app.models.chat import ChatModel
    from app.models.embedding import EmbeddingModel

logger = logging.getLogger(__name__)

_STORES_REGISTRY: dict[MemoryMode, type[MemoryStore]] = {}


def register_store(name: MemoryMode, store_cls: type[MemoryStore]) -> None:
    """注册记忆存储实现到全局注册表."""
    if name in _STORES_REGISTRY:
        return
    _STORES_REGISTRY[name] = store_cls


register_store(MemoryMode.MEMORY_BANK, MemoryBankStore)


def _make_store_key(mode: MemoryMode, user_id: str) -> str:
    return f"{mode.value}:{user_id}"


class MemoryModule:
    """统一记忆管理接口，Facade 模式."""

    def __init__(
        self,
        data_dir: Path,
        embedding_model: EmbeddingModel | None = None,
        chat_model: ChatModel | None = None,
    ) -> None:
        self._stores: dict[str, MemoryStore] = {}
        self._stores_lock = asyncio.Lock()
        self._data_dir = data_dir
        self._embedding_model = embedding_model
        self._chat_model = chat_model

    @property
    def chat_model(self) -> ChatModel:
        """获取聊天模型，延迟初始化."""
        if self._chat_model is None:
            self._chat_model = get_chat_model()
        return self._chat_model

    async def _get_store(
        self, mode: MemoryMode, user_id: str = "default"
    ) -> MemoryStore:
        key = _make_store_key(mode, user_id)
        if key not in self._stores:
            async with self._stores_lock:
                if key not in self._stores:
                    self._stores[key] = self._create_store(mode, user_id)
        return self._stores[key]

    @staticmethod
    def _resolve_mode(mode: MemoryMode | None) -> MemoryMode:
        return mode or MemoryMode.MEMORY_BANK

    def _create_store(self, mode: MemoryMode, user_id: str) -> MemoryStore:
        if mode not in _STORES_REGISTRY:
            raise UnknownModeError(mode)
        store_cls = _STORES_REGISTRY[mode]
        kwargs: dict[str, Any] = {"data_dir": self._data_dir}
        if getattr(store_cls, "requires_embedding", False):
            if self._embedding_model is None:
                self._embedding_model = get_cached_embedding_model()
            kwargs["embedding_model"] = self._embedding_model
        if getattr(store_cls, "requires_chat", False):
            if self._chat_model is None:
                self._chat_model = get_chat_model()
            kwargs["chat_model"] = self._chat_model
        kwargs["user_id"] = user_id
        return store_cls(**kwargs)

    def get_metrics(
        self, user_id: str = "default", mode: MemoryMode | None = None
    ) -> dict[str, Any] | None:
        """获取指定用户的指标快照。store 未初始化则返回 None。"""
        resolved = self._resolve_mode(mode)
        key = _make_store_key(resolved, user_id)
        store = self._stores.get(key)
        if store is None:
            return None
        m = getattr(store, "metrics", None)
        if m is None:
            return None
        return m.snapshot()

    async def write(
        self,
        event: MemoryEvent,
        *,
        mode: MemoryMode | None = None,
        user_id: str = "default",
    ) -> str:
        store = await self._get_store(self._resolve_mode(mode), user_id)
        return await store.write(event)

    async def write_interaction(
        self,
        query: str,
        response: str,
        event_type: str = "reminder",
        *,
        mode: MemoryMode | None = None,
        user_id: str = "default",
        **kwargs: object,
    ) -> InteractionResult:
        store = await self._get_store(self._resolve_mode(mode), user_id)
        if not getattr(store, "supports_interaction", False):
            msg = f"Store '{store.store_name}' does not support write_interaction"
            raise NotImplementedError(msg)
        return await store.write_interaction(query, response, event_type, **kwargs)

    async def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        mode: MemoryMode | None = None,
        user_id: str = "default",
    ) -> list[SearchResult]:
        store = await self._get_store(self._resolve_mode(mode), user_id)
        return await store.search(query, top_k=top_k)

    async def get_history(
        self,
        limit: int = 10,
        *,
        mode: MemoryMode | None = None,
        user_id: str = "default",
    ) -> list[MemoryEvent]:
        store = await self._get_store(self._resolve_mode(mode), user_id)
        return await store.get_history(limit)

    async def get_event_type(
        self,
        event_id: str,
        *,
        mode: MemoryMode | None = None,
        user_id: str = "default",
    ) -> str | None:
        store = await self._get_store(self._resolve_mode(mode), user_id)
        return await store.get_event_type(event_id)

    async def update_feedback(
        self,
        event_id: str,
        feedback: FeedbackData,
        *,
        mode: MemoryMode | None = None,
        user_id: str = "default",
    ) -> None:
        store = await self._get_store(self._resolve_mode(mode), user_id)
        await store.update_feedback(event_id, feedback)

    async def close(self) -> None:
        failed: list[str] = []
        for key, store in list(self._stores.items()):
            closer = getattr(store, "close", None)
            if closer is not None:
                try:
                    await closer()
                except Exception:
                    logger.exception("Failed to close store %s", key)
                    failed.append(key)
        if not failed:
            self._stores.clear()
        else:
            logger.warning("Stores not cleared due to close failures: %s", failed)
