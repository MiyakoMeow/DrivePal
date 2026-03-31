"""记忆适配器通用工具函数."""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from app.memory.interfaces import MemoryStore
from app.memory.schemas import MemoryEvent, SearchResult


class AdapterKwargs(Protocol):
    """记忆适配器方法接收的kwargs协议."""

    def get(self, key: str, default: object = None) -> object:
        """获取kwargs中的值."""
        ...


class VMBMode(StrEnum):
    """VMB基准测试用记忆类型枚举."""

    NONE = "none"
    GOLD = "gold"
    SUMMARY = "summary"
    KV = "kv"
    MEMORY_BANK = "memory_bank"


@dataclass
class BaselineMemory:
    """基线记忆的轻量容器."""

    memory_type: VMBMode
    memory_text: str = ""
    kv_store: dict[str, str] = field(default_factory=dict)


def history_to_interaction_records(history_text: str) -> list[MemoryEvent]:
    """将历史文本转换为交互记录."""
    if not history_text.strip():
        return []
    pattern = re.compile(r"^\[(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}\]\s+(.+)$")
    records = []
    for i, raw_line in enumerate(history_text.strip().splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        m = pattern.match(line)
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
            )
        )
    return records


def format_search_results(results: list[SearchResult]) -> tuple[str, int]:
    """将搜索结果格式化为文本和数量."""
    if not results:
        return ("", 0)
    texts = []
    for result in results:
        event = result.event if hasattr(result, "event") else result
        if isinstance(event, dict):
            content = event.get("content", "")
        elif hasattr(event, "content"):
            content = event.content
        else:
            content = str(event)
        if content:
            texts.append(content)
    return ("\n".join(texts), len(texts))


class StoreClient:
    """用于在记忆存储中搜索的客户端."""

    def __init__(self, store: MemoryStore) -> None:
        """使用存储实例初始化."""
        self.store = store

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        """在存储中搜索相关结果."""
        return self.store.search(query=query, top_k=top_k)
