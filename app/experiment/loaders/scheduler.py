from datasets import load_dataset, Dataset
from typing import List, Dict


class SchedulerLoader:
    """加载Scheduler数据集

    源: https://huggingface.co/datasets/shawnha/scheduler_dataset
    """

    _cache = None

    @classmethod
    def load(cls) -> Dataset:
        if cls._cache is None:
            cls._cache = load_dataset("shawnha/scheduler_dataset", split="train")

        if len(cls._cache) > 0:
            sample = cls._cache[0]
            required_cols = ["text"]
            missing = [c for c in required_cols if c not in sample]
            if missing:
                import logging

                logging.warning(f"Scheduler dataset missing columns: {missing}")

        return cls._cache

    @classmethod
    def get_test_cases(cls) -> List[Dict]:
        ds = cls.load()
        test_cases = []
        for i, row in enumerate(ds):
            text = row.get("text", "")
            if text:
                test_cases.append(
                    {
                        "input": text,
                        "type": cls._infer_type(text),
                        "id": f"scheduler_{i}",
                    }
                )
        return test_cases

    @classmethod
    def _infer_type(cls, text: str) -> str:
        text_lower = text.lower()
        if "flight" in text_lower or "机票" in text:
            return "flight_booking"
        if "hotel" in text_lower or "酒店" in text:
            return "hotel_booking"
        if "calendar" in text_lower or "日程" in text or "schedule" in text_lower:
            return "schedule_check"
        return "general"


def get_scheduler_test_cases() -> List[Dict]:
    """获取Scheduler测试用例"""
    return SchedulerLoader.get_test_cases()


if __name__ == "__main__":
    cases = get_scheduler_test_cases()
    print(f"Scheduler测试用例数: {len(cases)}")
    for c in cases[:3]:
        print(f"  - {c}")
