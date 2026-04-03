"""统一记忆管理接口，Facade 模式 + 工厂注册表."""

import asyncio
import logging
from typing import Any, Optional, TYPE_CHECKING

from app.memory.types import MemoryMode

if TYPE_CHECKING:
    from app.memory.schemas import FeedbackData, MemoryEvent, SearchResult
    from app.memory.interfaces import MemoryStore
    from pathlib import Path
    from app.models.embedding import EmbeddingModel
    from app.models.chat import ChatModel

logger = logging.getLogger(__name__)

_STORES_REGISTRY: dict[MemoryMode, type[MemoryStore]] = {}


def register_store(name: MemoryMode, store_cls: type[MemoryStore]) -> None:
    """注册记忆存储实现到全局注册表."""
    if name in _STORES_REGISTRY:
        return
    _STORES_REGISTRY[name] = store_cls


def _import_all_stores() -> None:
    from app.memory.stores.memory_bank import MemoryBankStore
    from app.memory.stores.memochat import MemoChatStore

    register_store(MemoryMode.MEMORY_BANK, MemoryBankStore)
    register_store(MemoryMode.MEMOCHAT, MemoChatStore)


_import_all_stores()


class MemoryModule:
    """统一记忆管理接口，Facade 模式."""

    def __init__(
        self,
        data_dir: Path,
        embedding_model: Optional["EmbeddingModel"] = None,
        chat_model: Optional["ChatModel"] = None,
    ) -> None:
        """初始化记忆模块."""
        self._stores: dict[MemoryMode, MemoryStore] = {}
        self._stores_lock = asyncio.Lock()
        self._data_dir = data_dir
        self._embedding_model = embedding_model
        self._chat_model = chat_model

    @property
    def chat_model(self) -> "ChatModel":
        """获取聊天模型，延迟初始化."""
        if self._chat_model is None:
            from app.models.settings import get_chat_model

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
            raise ValueError(
                f"Unknown mode: {mode}. Available: {list(_STORES_REGISTRY.keys())}"
            )
        store_cls = _STORES_REGISTRY[mode]
        kwargs: dict[str, Any] = {"data_dir": self._data_dir}
        if getattr(store_cls, "requires_embedding", False):
            if self._embedding_model is None:
                from app.models.settings import get_embedding_model

                self._embedding_model = get_embedding_model()
            kwargs["embedding_model"] = self._embedding_model
        if getattr(store_cls, "requires_chat", False):
            if self._chat_model is None:
                from app.models.settings import get_chat_model

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
        remind_at: str | None = None,
    ) -> str:
        """写入交互记录."""
        store = await self._get_store(self._resolve_mode(mode))
        if not getattr(store, "supports_interaction", False):
            raise NotImplementedError(
                f"Store '{store.store_name}' does not support write_interaction"
            )
        return await store.write_interaction(
            query, response, event_type, remind_at=remind_at
        )

    async def search(
        self, query: str, top_k: int = 10, *, mode: MemoryMode | None = None
    ) -> list[SearchResult]:
        """搜索记忆内容."""
        store = await self._get_store(self._resolve_mode(mode))
        return await store.search(query, top_k=top_k)

    async def get_history(
        self, limit: int = 10, *, mode: MemoryMode | None = None
    ) -> list[MemoryEvent]:
        """获取历史记忆事件."""
        store = await self._get_store(self._resolve_mode(mode))
        return await store.get_history(limit)

    async def update_feedback(
        self, event_id: str, feedback: FeedbackData, *, mode: MemoryMode | None = None
    ) -> None:
        """更新记忆反馈."""
        store = await self._get_store(self._resolve_mode(mode))
        await store.update_feedback(event_id, feedback)
