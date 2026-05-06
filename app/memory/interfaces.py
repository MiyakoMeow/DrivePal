"""MemoryStore 结构化接口定义（Protocol）及所有子组件依赖抽象。"""

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

    from app.memory.schemas import (
        FeedbackData,
        InteractionResult,
        MemoryEvent,
        SearchResult,
    )
    from app.models.chat import ChatModel
    from app.models.embedding import EmbeddingModel


class MemoryStore(Protocol):
    """通用记忆存储接口。"""

    store_name: str

    @classmethod
    def create_default_config(
        cls,
        data_dir: Path,
        embedding_model: EmbeddingModel | None,
        chat_model: ChatModel | None,
    ) -> Any:
        """构造默认配置对象。"""
        ...

    async def write(self, event: MemoryEvent) -> str:
        """写入一条记忆事件。"""
        ...

    async def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        """搜索相关记忆。"""
        ...

    async def get_history(self, limit: int = 10) -> list[MemoryEvent]:
        """获取历史记忆事件。"""
        ...

    async def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        """更新记忆反馈。"""
        ...

    async def get_event_type(self, event_id: str) -> str | None:
        """按 event_id 查找事件类型。"""
        ...


@runtime_checkable
class InteractiveMemoryStore(MemoryStore, Protocol):
    """支持交互记录的扩展接口。"""

    async def write_interaction(
        self,
        query: str,
        response: str,
        event_type: str = "reminder",
    ) -> InteractionResult:
        """写入一次用户交互记录。"""
        ...


class VectorIndex(Protocol):
    """向量索引抽象（FaissIndex 契约）。"""

    async def load(self) -> None:
        """从磁盘加载索引。"""
        ...

    async def save(self) -> None:
        """持久化索引到磁盘。"""
        ...

    async def add_vector(
        self,
        text: str,
        embedding: list[float],
        timestamp: str,
        extra_meta: dict | None = None,
    ) -> int:
        """添加向量并关联文本与元数据。"""
        ...

    async def search(self, query_emb: list[float], top_k: int) -> list[dict]:
        """检索最相似的 top_k 条向量。"""
        ...

    async def remove_vectors(self, faiss_ids: list[int]) -> None:
        """从索引移除指定向量。"""
        ...

    def get_metadata(self) -> list[dict]:
        """返回所有元数据（可变引用）。"""
        ...

    def get_metadata_by_id(self, faiss_id: int) -> dict | None:
        """按 faiss_id 查找元数据条目。"""
        ...

    def get_extra(self) -> dict:
        """返回额外元数据（总体摘要/人格）。"""
        ...

    def set_extra(self, extra: dict) -> None:
        """设置额外元数据。"""
        ...

    @property
    def total(self) -> int:
        """索引中向量总数。"""
        ...


class ForgettingStrategy(Protocol):
    """遗忘策略抽象。"""

    def maybe_forget(
        self, metadata: list[dict], reference_date: str | None = None
    ) -> list[int] | None:
        """检查并标记应遗忘的条目。"""
        ...


class RetrievalStrategy(Protocol):
    """检索管道抽象。"""

    async def search(self, query: str, top_k: int = 5) -> list[dict]:
        """执行检索管道，返回排序结果。"""
        ...


class FeedbackHandler(Protocol):
    """反馈处理抽象。"""

    async def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        """处理一次用户反馈。"""
        ...


class SummarizationService(Protocol):
    """摘要/人格生成抽象。"""

    async def get_daily_summary(self, date_key: str) -> str | None:
        """生成某天摘要（已有则不覆盖）。"""
        ...

    async def get_overall_summary(self) -> str | None:
        """生成总体摘要（已有则不覆盖）。"""
        ...

    async def get_daily_personality(self, date_key: str) -> str | None:
        """生成某天人格画像（已有则不覆盖）。"""
        ...

    async def get_overall_personality(self) -> str | None:
        """生成总体人格画像（已有则不覆盖）。"""
        ...


class SearchEnricher(Protocol):
    """搜索结果上下文注入策略抽象。"""

    async def enrich(
        self, results: list[SearchResult], extra: dict
    ) -> list[SearchResult]:
        """向搜索结果注入额外上下文。"""
        ...
