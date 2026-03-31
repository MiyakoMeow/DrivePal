"""键值对基线适配器."""

from pathlib import Path
from typing import Any

from adapters.memory_adapters.common import BaselineMemory, MemoryType


class KVAdapter:
    """键值对记忆基线,调用 VMB 的 build_memory_key_value."""

    TAG = MemoryType.KV

    def __init__(self, data_dir: Path) -> None:
        """使用数据目录初始化."""
        self.data_dir = data_dir

    def add(self, history_text: str, **kwargs: dict[str, Any]) -> BaselineMemory:
        """构建键值对记忆."""
        agent_client = kwargs.get("agent_client")
        if not agent_client:
            return BaselineMemory(memory_type=MemoryType.KV)

        from adapters.runner import setup_vehiclemembench_path

        setup_vehiclemembench_path()
        from evaluation.model_evaluation import (
            build_memory_key_value,
            split_history_by_day,
        )

        daily = split_history_by_day(history_text)
        store, _, _ = build_memory_key_value(agent_client, daily)
        return BaselineMemory(memory_type=MemoryType.KV, kv_store=store.to_dict())

    def get_search_client(self, store: BaselineMemory) -> None:
        """不支持搜索客户端."""
        raise NotImplementedError("KVAdapter does not support search client")
