"""DatasetLoader Protocol 定义."""

from typing import Protocol

from datasets import Dataset


class DatasetLoader(Protocol):
    """数据集加载器接口."""

    def load(self) -> Dataset:
        """加载数据集."""
        ...

    def get_test_cases(self) -> list[dict]:
        """获取测试用例."""
        ...
