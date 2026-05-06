"""MemoryStore 结构化接口定义（Protocol）及所有子组件依赖抽象。"""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from app.memory.schemas import (
        FeedbackData,
        InteractionResult,
        MemoryEvent,
        SearchResult,
    )


class MemoryStore(Protocol):
    """通用记忆存储接口。"""

    store_name: str

    async def write(self, event: MemoryEvent) -> str: ...
    async def search(self, query: str, top_k: int = 10) -> list[SearchResult]: ...
    async def get_history(self, limit: int = 10) -> list[MemoryEvent]: ...
    async def update_feedback(self, event_id: str, feedback: FeedbackData) -> None: ...
    async def get_event_type(self, event_id: str) -> str | None: ...


@runtime_checkable
class InteractiveMemoryStore(MemoryStore, Protocol):
    """支持交互记录的扩展接口。"""

    async def write_interaction(
        self,
        query: str,
        response: str,
        event_type: str = "reminder",
    ) -> InteractionResult: ...


class VectorIndex(Protocol):
    """向量索引抽象（FaissIndex 契约）。"""

    async def load(self) -> None: ...
    async def save(self) -> None: ...
    async def add_vector(
        self,
        text: str,
        embedding: list[float],
        timestamp: str,
        extra_meta: dict | None = None,
    ) -> int: ...
    async def search(self, query_emb: list[float], top_k: int) -> list[dict]: ...
    async def remove_vectors(self, faiss_ids: list[int]) -> None: ...
    def get_metadata(self) -> list[dict]: ...
    def get_metadata_by_id(self, faiss_id: int) -> dict | None: ...
    def get_extra(self) -> dict: ...
    def set_extra(self, extra: dict) -> None: ...
    @property
    def total(self) -> int: ...


class ForgettingStrategy(Protocol):
    """遗忘策略抽象。"""

    def maybe_forget(
        self, metadata: list[dict], reference_date: str | None = None
    ) -> list[int] | None: ...


class RetrievalStrategy(Protocol):
    """检索管道抽象。"""

    async def search(self, query: str, top_k: int = 5) -> list[dict]: ...


class FeedbackHandler(Protocol):
    """反馈处理抽象。"""

    async def update_feedback(self, event_id: str, feedback: FeedbackData) -> None: ...


class SummarizationService(Protocol):
    """摘要/人格生成抽象。"""

    async def get_daily_summary(self, date_key: str) -> str | None: ...
    async def get_overall_summary(self) -> str | None: ...
    async def get_daily_personality(self, date_key: str) -> str | None: ...
    async def get_overall_personality(self) -> str | None: ...


class SearchEnricher(Protocol):
    """搜索结果上下文注入策略抽象。"""

    async def enrich(
        self, results: list[SearchResult], extra: dict
    ) -> list[SearchResult]: ...
