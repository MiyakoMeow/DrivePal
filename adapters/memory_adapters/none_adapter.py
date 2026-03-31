from pathlib import Path

from adapters.memory_adapters.common import BaselineMemory


class NoneAdapter:
    TAG = "none"

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def add(self, history_text: str, **kwargs) -> BaselineMemory:
        return BaselineMemory(memory_type="none")

    def get_search_client(self, store: BaselineMemory) -> None:
        raise NotImplementedError("NoneAdapter does not support search client")
