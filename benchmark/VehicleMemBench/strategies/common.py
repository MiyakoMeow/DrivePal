"""记忆适配器通用工具函数."""

import re
from typing import TYPE_CHECKING

from app.memory.schemas import MemoryEvent, SearchResult

if TYPE_CHECKING:
    from app.memory.interfaces import MemoryStore

_TIMESTAMP_PATTERN = re.compile(r"^\[(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}\]\s+(.+)$")


def history_to_interaction_records(history_text: str) -> list[MemoryEvent]:
    """将历史文本转换为交互记录."""
    if not history_text.strip():
        return []
    records = []
    for i, raw_line in enumerate(history_text.strip().splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        m = _TIMESTAMP_PATTERN.match(line)
        if m:
            date_group = m.group(1)
            content = m.group(2)
        else:
            date_group = "unknown"
            content = line
        records.append(
            MemoryEvent(
                id=f"hist_{i}",
                content=content,
                description=content,
                type="general",
                date_group=date_group,
                memory_strength=1,
            ),
        )
    return records


def format_search_results(results: list[SearchResult]) -> tuple[str, int]:
    """将搜索结果格式化为结构化文本和数量."""
    if not results:
        return ("", 0)
    texts = []
    for idx, r in enumerate(results, 1):
        event = r.event if isinstance(r.event, dict) else {}
        content = str(event.get("content", "")) if event else ""
        if not content:
            continue
        date_group = event.get("date_group", "unknown")
        source = r.source
        strength = event.get("memory_strength", "?")
        parts = [
            f"--- Memory Result {idx} ---",
            f"Date: {date_group} | Source: {source} | Strength: {strength}",
            f"Content: {content}",
        ]
        if r.interactions:
            parts.append("Related interactions:")
            for i, interaction in enumerate(r.interactions, 1):
                q = interaction.get("query", "")
                resp = interaction.get("response", "")
                parts.append(f"  [{i}] Query: {q}")
                if resp:
                    parts.append(f"      Response: {resp}")
        texts.append("\n".join(parts))
    return ("\n\n".join(texts), len(texts))


class StoreClient:
    """用于在记忆存储中搜索的客户端."""

    def __init__(self, store: MemoryStore) -> None:
        """使用存储实例初始化."""
        self._store = store

    async def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        """在存储中搜索相关结果."""
        return await self._store.search(query=query, top_k=top_k)
