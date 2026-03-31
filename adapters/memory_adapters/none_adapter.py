"""无记忆基线适配器."""

from pathlib import Path

from adapters.memory_adapters.common import BaselineMemory


class NoneAdapter:
    """无记忆基线，不存储任何信息."""

    TAG = "none"

    def __init__(self, data_dir: Path) -> None:
        """使用数据目录初始化."""
        self.data_dir = data_dir

    def add(self, history_text: str, **kwargs: dict) -> BaselineMemory:
        """返回空的基线记忆."""
        return BaselineMemory(memory_type="none")

    def get_search_client(self, store: BaselineMemory) -> None:
        """不支持搜索客户端."""
        raise NotImplementedError("NoneAdapter does not support search client")
