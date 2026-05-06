"""搜索结果上下文注入策略实现。"""

from typing import TYPE_CHECKING

from app.memory.schemas import SearchResult
from app.memory.stores.memory_bank.summarizer import GENERATION_EMPTY

if TYPE_CHECKING:
    from app.memory.interfaces import VectorIndex


class OverallContextEnricher:
    """搜索结果上下文注入器。内部从 VectorIndex 获取 extra。"""

    def __init__(
        self,
        index: VectorIndex | None = None,
        keys: list[tuple[str, str]] | None = None,
    ) -> None:
        """初始化 enricher。

        Args:
            index: VectorIndex 实例，用于获取 extra 元数据。
            keys: (extra_key, label) 对列表。

        """
        self._index = index
        self._keys = keys or [
            ("overall_summary", "Overall summary of past memories"),
            ("overall_personality", "User vehicle preferences and habits"),
        ]

    async def enrich(
        self,
        results: list[SearchResult],
        extra: dict | None = None,
    ) -> list[SearchResult]:
        """在 results 前置全局上下文摘要/人格信息。

        兼容旧调用方：可传 extra dict，也可由内部从 index 获取。
        """
        if extra is None:
            if self._index is None:
                return results
            extra = self._index.get_extra()
        prepend = []
        for key, label in self._keys:
            val = extra.get(key, "")
            if val and val != GENERATION_EMPTY:
                prepend.append(f"{label}: {val}")
        if not prepend:
            return results
        out: list[SearchResult] = [
            SearchResult(
                event={"content": "\n".join(prepend), "type": "overall_context"},
                score=float("inf"),
                source="overall",
            )
        ]
        out.extend(results)
        return out
