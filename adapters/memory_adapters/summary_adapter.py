from pathlib import Path

from adapters.memory_adapters.common import BaselineMemory


class SummaryAdapter:
    TAG = "summary"

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def add(self, history_text: str, **kwargs) -> BaselineMemory:
        agent_client = kwargs.get("agent_client")
        if not agent_client:
            return BaselineMemory(memory_type="summary")

        from adapters.runner import setup_vehiclemembench_path

        setup_vehiclemembench_path()
        from evaluation.model_evaluation import (
            build_memory_recursive_summary,
            split_history_by_day,
        )

        daily = split_history_by_day(history_text)
        mem_text, _, _ = build_memory_recursive_summary(agent_client, daily)
        return BaselineMemory(memory_type="summary", memory_text=mem_text)

    def get_search_client(self, store: BaselineMemory) -> None:
        raise NotImplementedError("SummaryAdapter does not support search client")
