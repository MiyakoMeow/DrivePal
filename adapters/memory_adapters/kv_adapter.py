from pathlib import Path

from adapters.memory_adapters.common import BaselineMemory


class KVAdapter:
    TAG = "kv"

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def add(self, history_text: str, **kwargs) -> BaselineMemory:
        agent_client = kwargs.get("agent_client")
        if not agent_client:
            return BaselineMemory(memory_type="kv")

        from adapters.runner import setup_vehiclemembench_path

        setup_vehiclemembench_path()
        from evaluation.model_evaluation import (
            build_memory_key_value,
            split_history_by_day,
        )

        daily = split_history_by_day(history_text)
        store, _, _ = build_memory_key_value(agent_client, daily)
        return BaselineMemory(memory_type="kv", kv_store=store.to_dict())

    def get_search_client(self, store: BaselineMemory) -> None:
        raise NotImplementedError("KVAdapter does not support search client")
