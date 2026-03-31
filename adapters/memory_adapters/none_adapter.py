"""无记忆基线适配器."""

from pathlib import Path
from typing import Any

from adapters.memory_adapters.common import BaselineMemory, VMBMode


class NoneAdapter:
    """无记忆基线，不存储任何信息."""

    TAG = VMBMode.NONE

    def __init__(self, data_dir: Path) -> None:
        """使用数据目录初始化."""
        self.data_dir = data_dir

    def add(self, history_text: str, **kwargs: Any) -> BaselineMemory:
        """返回空的基线记忆."""
        return BaselineMemory(memory_type=VMBMode.NONE)

    def get_search_client(self, store: BaselineMemory) -> None:
        """不支持搜索客户端."""
        msg = "NoneAdapter does not support search client"
        raise NotImplementedError(msg)
