from app.experiment.loaders.sgd_calendar import get_sgd_calendar_test_cases
from app.experiment.loaders.scheduler import get_scheduler_test_cases
from typing import List, Dict


class DatasetLoader:
    """数据集加载器 - 整合HuggingFace数据集"""

    @staticmethod
    def get_test_cases(dataset: str) -> List[Dict]:
        if dataset == "sgd_calendar":
            return get_sgd_calendar_test_cases()
        elif dataset == "scheduler":
            return get_scheduler_test_cases()
        else:
            raise ValueError(f"Unknown dataset: {dataset}")
