"""统一记忆管理接口，Facade 模式 + 工厂注册表."""

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from app.memory.stores.memory_bank import MemoryBankStore
from app.memory.types import MemoryMode
from app.models.chat import get_chat_model
from app.models.embedding import get_cached_embedding_model


class UnknownModeError(ValueError):
    """未知记忆模式异常."""

    MSG = "Unknown mode: {mode}"

    def __init__(self, mode: MemoryMode) -> None:
        """初始化异常，使用类常量消息格式化 mode."""
        super().__init__(self.MSG.format(mode=mode))


if TYPE_CHECKING:
    from pathlib import Path

    from app.memory.interfaces import MemoryStore
    from app.memory.schemas import FeedbackData, MemoryEvent, SearchResult
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


class MemoryModule:
    """统一记忆管理接口，Facade 模式."""

    def __init__(
        self,
        data_dir: Path,
        embedding_model: EmbeddingModel | None = None,
        chat_model: ChatModel | None = None,
    ) -> None:
        """初始化记忆模块."""
        self._stores: dict[MemoryMode, MemoryStore] = {}
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

    async def _get_store(self, mode: MemoryMode) -> MemoryStore:
        if mode not in self._stores:
            async with self._stores_lock:
                if mode not in self._stores:
                    self._stores[mode] = self._create_store(mode)
        return self._stores[mode]

    def _resolve_mode(self, mode: MemoryMode | None) -> MemoryMode:
        """解析 mode 参数，默认 MEMORY_BANK."""
        return mode or MemoryMode.MEMORY_BANK

    def _create_store(self, mode: MemoryMode) -> MemoryStore:
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
        return store_cls(**kwargs)

    async def write(self, event: MemoryEvent, *, mode: MemoryMode | None = None) -> str:
        """写入记忆事件."""
        store = await self._get_store(self._resolve_mode(mode))
        return await store.write(event)

    async def write_interaction(
        self,
        query: str,
        response: str,
        event_type: str = "reminder",
        *,
        mode: MemoryMode | None = None,
    ) -> str:
        """写入交互记录."""
        store = await self._get_store(self._resolve_mode(mode))
        if not getattr(store, "supports_interaction", False):
            msg = f"Store '{store.store_name}' does not support write_interaction"
            raise NotImplementedError(msg)
        return await store.write_interaction(query, response, event_type)

    async def search(
        self,
        query: str,
        top_k: int = 10,
        *,
        mode: MemoryMode | None = None,
    ) -> list[SearchResult]:
        """搜索记忆内容."""
        store = await self._get_store(self._resolve_mode(mode))
        return await store.search(query, top_k=top_k)

    async def get_history(
        self,
        limit: int = 10,
        *,
        mode: MemoryMode | None = None,
    ) -> list[MemoryEvent]:
        """获取历史记忆事件."""
        store = await self._get_store(self._resolve_mode(mode))
        return await store.get_history(limit)

    async def update_feedback(
        self,
        event_id: str,
        feedback: FeedbackData,
        *,
        mode: MemoryMode | None = None,
    ) -> None:
        """更新记忆反馈."""
        store = await self._get_store(self._resolve_mode(mode))
        await store.update_feedback(event_id, feedback)
