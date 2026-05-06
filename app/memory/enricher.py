"""搜索结果上下文注入策略实现。"""

from app.memory.schemas import SearchResult
from app.memory.stores.memory_bank.summarizer import GENERATION_EMPTY


class OverallContextEnricher:
    """注入 overall_summary + overall_personality 到搜索结果前置。

    通过可配置的 (extra_key, label) 对列表支持扩展。
    """

    def __init__(self, keys: list[tuple[str, str]] | None = None) -> None:
        """初始化 enricher。

        Args:
            keys: (extra_key, label) 对列表。
                  默认注入 overall_summary 和 overall_personality。

        """
        self._keys = keys or [
            ("overall_summary", "Overall summary of past memories"),
            ("overall_personality", "User vehicle preferences and habits"),
        ]

    async def enrich(
        self,
        results: list[SearchResult],
        extra: dict,
    ) -> list[SearchResult]:
        """在 results 前置全局上下文摘要/人格信息。"""
        prepend = []
        for key, label in self._keys:
            val = extra.get(key, "")
            if val and val != GENERATION_EMPTY:
                prepend.append(f"{label}: {val}")
        if not prepend:
            return results
        out: list[SearchResult] = []
        out.append(
            SearchResult(
                event={"content": "\n".join(prepend), "type": "overall_context"},
                score=float("inf"),
                source="overall",
            )
        )
        top_k = len(results)
        out.extend(results[: max(0, top_k - 1)])
        return out
