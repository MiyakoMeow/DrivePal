"""DatasetLoader Protocol 定义."""

from typing import Protocol

from datasets import Dataset


class DatasetLoader(Protocol):
    """数据集加载器接口."""

    def load(self) -> Dataset: ...
    def get_test_cases(self) -> list[dict]: ...
