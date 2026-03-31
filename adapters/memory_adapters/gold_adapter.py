from pathlib import Path

from adapters.memory_adapters.common import BaselineMemory


class GoldAdapter:
    TAG = "gold"

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def add(self, history_text: str, **kwargs) -> BaselineMemory:
        return BaselineMemory(memory_type="gold")

    def get_search_client(self, store: BaselineMemory) -> None:
        raise NotImplementedError("GoldAdapter does not support search client")
