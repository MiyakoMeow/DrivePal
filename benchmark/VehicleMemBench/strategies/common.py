"""记忆适配器通用工具函数."""

import re
from typing import TYPE_CHECKING

from app.memory.schemas import MemoryEvent, SearchResult

if TYPE_CHECKING:
    from app.memory.interfaces import MemoryStore

_LINE_PATTERN = re.compile(r"^\[(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}\]\s+([^:]+):\s(.+)$")


def history_to_interaction_records(history_text: str) -> list[MemoryEvent]:
    """将历史文本按 (date, speaker) 分组转换为交互记录."""
    if not history_text.strip():
        return []
    groups: dict[tuple[str, str], list[str]] = {}
    for _, raw_line in enumerate(history_text.strip().splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        m = _LINE_PATTERN.match(line)
        if m:
            date_group = m.group(1)
            speaker_name = m.group(2).strip()
            content = m.group(3)
        else:
            date_group = "unknown"
            speaker_name = "unknown"
            content = line
        key = (date_group, speaker_name)
        groups.setdefault(key, []).append(f"{speaker_name}: {content}")
    records = []
    for (date_group, speaker_name), lines in groups.items():
        records.append(
            MemoryEvent(
                id=f"hist_{date_group}_{speaker_name}",
                content="\n".join(lines),
                description="",
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
        if isinstance(r.event, dict):
            event = r.event
        elif hasattr(r.event, "content"):
            event = {"content": getattr(r.event, "content", "")}
        else:
            event = {"content": str(r.event) if r.event is not None else ""}
        content = str(event.get("content", ""))
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
