"""统一记忆管理接口，Facade 模式 + 工厂注册表."""

from typing import Any, Optional, TYPE_CHECKING

from app.memory.interfaces import MemoryStore
from app.memory.types import MemoryMode

if TYPE_CHECKING:
    from app.models.chat import ChatModel
    from app.models.embedding import EmbeddingModel

_STORES_REGISTRY: dict[MemoryMode, type[MemoryStore]] = {}


def register_store(name: MemoryMode, store_cls: type[MemoryStore]) -> None:
    """注册 MemoryStore 实现类，用于工厂创建."""
    _STORES_REGISTRY[name] = store_cls


def _import_all_stores() -> None:
    """延迟导入所有 store 类并注册到工厂注册表."""
    from app.memory.stores.keyword_store import KeywordMemoryStore
    from app.memory.stores.llm_store import LLMOnlyMemoryStore
    from app.memory.stores.embedding_store import EmbeddingMemoryStore
    from app.memory.stores.memory_bank_store import MemoryBankStore

    register_store(MemoryMode.KEYWORD, KeywordMemoryStore)
    register_store(MemoryMode.LLM_ONLY, LLMOnlyMemoryStore)
    register_store(MemoryMode.EMBEDDINGS, EmbeddingMemoryStore)
    register_store(MemoryMode.MEMORY_BANK, MemoryBankStore)


class MemoryModule:
    """统一记忆管理接口，Facade 模式."""

    def __init__(
        self,
        data_dir: str,
        embedding_model: Optional["EmbeddingModel"] = None,
        chat_model: Optional["ChatModel"] = None,
    ):
        """初始化 MemoryModule 实例.

        Args:
            data_dir: 数据存储目录.
            embedding_model: 向量嵌入模型 (可选，未传则按需加载).
            chat_model: 聊天模型 (可选，未传则按需加载).

        """
        _import_all_stores()
        self._stores: dict[MemoryMode, MemoryStore] = {}
        self._data_dir = data_dir
        self._embedding_model = embedding_model
        self._chat_model = chat_model
        self._default_mode: MemoryMode = MemoryMode.MEMORY_BANK

    @property
    def chat_model(self):
        """返回聊天模型实例."""
        if self._chat_model is None:
            from app.models.settings import get_chat_model

            self._chat_model = get_chat_model()
        return self._chat_model

    def _get_store(self, mode: MemoryMode) -> MemoryStore:
        """懒加载获取指定模式的 store."""
        if mode not in self._stores:
            self._stores[mode] = self._create_store(mode)
        return self._stores[mode]

    def _create_store(self, mode: MemoryMode) -> MemoryStore:
        """工厂方法创建 store，根据 Store 类属性按需加载模型."""
        if mode not in _STORES_REGISTRY:
            raise ValueError(
                f"Unknown mode: {mode}. Available: {list(_STORES_REGISTRY.keys())}"
            )
        store_cls = _STORES_REGISTRY[mode]
        kwargs: dict[str, Any] = {"data_dir": self._data_dir}
        if store_cls.requires_embedding:
            if self._embedding_model is None:
                from app.models.settings import get_embedding_model

                self._embedding_model = get_embedding_model()
            kwargs["embedding_model"] = self._embedding_model
        if store_cls.requires_chat:
            if self._chat_model is None:
                from app.models.settings import get_chat_model

                self._chat_model = get_chat_model()
            kwargs["chat_model"] = self._chat_model
        return store_cls(**kwargs)

    def set_default_mode(self, mode: MemoryMode) -> None:
        """设置默认模式."""
        if mode not in _STORES_REGISTRY:
            raise ValueError(f"Unknown mode: {mode}")
        self._default_mode = mode

    def write(self, event: dict) -> str:
        """写入事件到当前模式的 store."""
        store = self._get_store(self._default_mode)
        return store.write(event)

    def write_interaction(
        self, query: str, response: str, event_type: str = "reminder"
    ) -> str:
        """写入交互记录."""
        store = self._get_store(self._default_mode)
        return store.write_interaction(query, response, event_type)

    def search(self, query: str, mode: MemoryMode | None = None) -> list:
        """检索记忆."""
        target_mode = mode or self._default_mode
        return self._get_store(target_mode).search(query)

    def get_history(self, limit: int = 10) -> list:
        """获取历史记录."""
        return self._get_store(self._default_mode).get_history(limit)

    def update_feedback(self, event_id: str, feedback: dict) -> None:
        """更新反馈."""
        self._get_store(self._default_mode).update_feedback(event_id, feedback)
