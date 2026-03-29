"""数据集加载器模块."""

from collections.abc import Callable

from app.experiment.loaders.base import DatasetLoader
from app.experiment.loaders.scheduler import SchedulerLoader
from app.experiment.loaders.sgd_calendar import SGDCalendarLoader

_LOADERS: dict[str, Callable[[], DatasetLoader]] = {
    "sgd_calendar": SGDCalendarLoader,
    "scheduler": SchedulerLoader,
}


def get_test_cases(dataset: str) -> list[dict]:
    """根据数据集名称获取测试用例."""
    if dataset not in _LOADERS:
        raise ValueError(f"Unknown dataset: {dataset}")
    return _LOADERS[dataset]().get_test_cases()
