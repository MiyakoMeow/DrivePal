"""统一记忆管理接口，Facade 模式 + 工厂注册表."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, cast

from app.memory.components import FeedbackManager
from app.memory.enricher import OverallContextEnricher
from app.memory.interfaces import InteractiveMemoryStore, VectorIndex
from app.memory.stores.memory_bank import MemoryBankStore, MemoryBankStoreConfig
from app.memory.stores.memory_bank.faiss_index import FaissIndex
from app.memory.stores.memory_bank.forget import ForgettingCurve
from app.memory.stores.memory_bank.llm import LlmClient
from app.memory.stores.memory_bank.retrieval import RetrievalPipeline
from app.memory.stores.memory_bank.summarizer import Summarizer
from app.memory.types import MemoryMode
from app.memory.worker import BackgroundWorker
from app.models.chat import ChatModel, get_chat_model
from app.models.embedding import EmbeddingModel, get_cached_embedding_model


class UnknownModeError(ValueError):
    """未知记忆模式异常."""

    MSG = "Unknown mode: {mode}"

    def __init__(self, mode: MemoryMode) -> None:
        """初始化异常，使用类常量消息格式化 mode."""
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

    def _resolve_embedding(self, store_cls: type[MemoryStore]) -> EmbeddingModel:
        """返回嵌入模型，按 store 需求初始化。"""
        if self._embedding_model is None and getattr(
            store_cls, "requires_embedding", False
        ):
            self._embedding_model = get_cached_embedding_model()
        if getattr(store_cls, "requires_embedding", False):
            if self._embedding_model is None:
                msg = f"Store {store_cls.store_name} requires embedding_model"
                raise RuntimeError(msg)
            return self._embedding_model
        return cast("EmbeddingModel", self._embedding_model)

    def _resolve_chat(self, store_cls: type[MemoryStore]) -> ChatModel | None:
        """返回聊天模型，按 store 需求初始化。"""
        if self._chat_model is None and getattr(store_cls, "requires_chat", False):
            self._chat_model = get_chat_model()
        if getattr(store_cls, "requires_chat", False):
            return self._chat_model
        return None

    def _create_store(self, mode: MemoryMode) -> MemoryStore:
        if mode not in _STORES_REGISTRY:
            raise UnknownModeError(mode)
        store_cls = _STORES_REGISTRY[mode]

        data_dir = self._data_dir

        index: VectorIndex = FaissIndex(data_dir)
        embedding = self._resolve_embedding(store_cls)
        chat = self._resolve_chat(store_cls)

        retrieval = RetrievalPipeline(index, embedding)
        forgetting = ForgettingCurve()
        feedback = FeedbackManager(data_dir)

        summarizer_svc = None
        background = None
        if chat:
            llm = LlmClient(chat)
            summarizer_svc = Summarizer(llm, index)
            background = BackgroundWorker(index, summarizer_svc, embedding)

        enricher = OverallContextEnricher()

        config = MemoryBankStoreConfig(
            index=index,
            retrieval=retrieval,
            embedding_model=embedding,
            enricher=enricher,
            forgetting=forgetting,
            feedback=feedback,
            background=background,
        )
        return store_cls(config)

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
    ) -> InteractionResult:
        """写入交互记录."""
        store = await self._get_store(self._resolve_mode(mode))
        if not isinstance(store, InteractiveMemoryStore):
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

    async def get_event_type(
        self,
        event_id: str,
        *,
        mode: MemoryMode | None = None,
    ) -> str | None:
        """按 event_id 查找事件类型."""
        store = await self._get_store(self._resolve_mode(mode))
        return await store.get_event_type(event_id)

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
