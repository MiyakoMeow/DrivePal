"""结合嵌入向量和LLM的记忆库适配器."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.memory.stores.memory_bank import MemoryBankStore
from app.models.settings import NoDefaultModelGroupError
from vendor_adapter.VehicleMemBench.memory_adapters.common import (
    StoreClient,
    history_to_interaction_records,
)
from vendor_adapter.VehicleMemBench.model_config import (
    get_store_chat_model,
    get_store_embedding_model,
)

if TYPE_CHECKING:
    from pathlib import Path

    from app.memory.interfaces import MemoryStore

logger = logging.getLogger(__name__)


class MemoryBankAdapterError(Exception):
    """MemoryBankAdapter 相关错误."""


class MemoryBankAdapter:
    """结合嵌入向量和LLM进行记忆搜索的适配器."""

    TAG = "memory_bank"

    def __init__(self, data_dir: Path) -> None:
        """使用数据目录初始化."""
        self.data_dir = data_dir

    def _validate_data_dir(self) -> None:
        """验证数据目录有效."""
        if not self.data_dir.exists():
            self.data_dir.mkdir(parents=True, exist_ok=True)
        elif not self.data_dir.is_dir():
            msg = f"data_dir is not a directory: {self.data_dir}"
            raise MemoryBankAdapterError(msg)

    async def add(self, history_text: str) -> MemoryBankStore:
        """将历史文本添加到记忆库存储."""
        self._validate_data_dir()
        try:
            chat_model = get_store_chat_model()
            embedding_model = get_store_embedding_model()
        except NoDefaultModelGroupError as e:
            msg = (
                "Failed to initialize chat/embedding model for MemoryBankAdapter: "
                "no default model group configured"
            )
            raise MemoryBankAdapterError(msg) from e

        store = MemoryBankStore(
            data_dir=self.data_dir,
            chat_model=chat_model,
            embedding_model=embedding_model,
        )
        records = history_to_interaction_records(history_text)
        if not records:
            return store
        try:
            for record in records:
                await store.write(record)
        except Exception as e:
            msg = f"Failed to write {len(records)} records to MemoryBankStore"
            raise MemoryBankAdapterError(msg) from e
        return store

    def load(self) -> MemoryBankStore:
        """从已有数据目录加载记忆库存储（无需重放写入）."""
        self._validate_data_dir()
        try:
            return MemoryBankStore(
                data_dir=self.data_dir,
                chat_model=get_store_chat_model(),
                embedding_model=get_store_embedding_model(),
            )
        except (NoDefaultModelGroupError, RuntimeError) as e:
            msg = (
                "Failed to initialize chat/embedding model for MemoryBankAdapter: "
                "no default model group configured or embedding provider missing"
            )
            raise MemoryBankAdapterError(msg) from e

    def get_search_client(self, store: MemoryStore) -> StoreClient:
        """获取存储的搜索客户端."""
        return StoreClient(store)
