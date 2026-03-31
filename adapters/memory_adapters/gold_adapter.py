"""Gold 标准基线适配器."""

from pathlib import Path
from typing import Any

from adapters.memory_adapters.common import BaselineMemory


class GoldAdapter:
    """Gold 标准记忆基线，使用标注数据."""

    TAG = "gold"

    def __init__(self, data_dir: Path) -> None:
        """使用数据目录初始化."""
        self.data_dir = data_dir

    def add(self, history_text: str, **kwargs: dict[str, Any]) -> BaselineMemory:
        """返回空 BaselineMemory, gold memory 在 run 阶段从 event 获取."""
        return BaselineMemory(memory_type="gold")

    def get_search_client(self, store: BaselineMemory) -> None:
        """不支持搜索客户端."""
        raise NotImplementedError("GoldAdapter does not support search client")
