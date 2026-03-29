"""Scheduler数据集加载模块."""

import logging

from datasets import Dataset, load_dataset

_cache = None


class SchedulerLoader:
    """加载Scheduler数据集.

    源: https://huggingface.co/datasets/shawnha/scheduler_dataset
    """

    def load(self) -> Dataset:
        """加载 Scheduler 数据集."""
        global _cache
        if _cache is None:
            _cache = load_dataset("shawnha/scheduler_dataset", split="train")

        if len(_cache) > 0:
            sample = _cache[0]
            required_cols = ["text"]
            missing = [c for c in required_cols if c not in sample]
            if missing:
                logging.warning(f"Scheduler dataset missing columns: {missing}")

        return _cache

    def get_test_cases(self) -> list[dict]:
        """从数据集提取测试用例."""
        ds = self.load()
        test_cases = []
        for i, row in enumerate(ds):
            text = row.get("text", "")
            if text:
                test_cases.append(
                    {
                        "input": text,
                        "type": self._infer_type(text),
                        "id": f"scheduler_{i}",
                    },
                )
        return test_cases

    def _infer_type(self, text: str) -> str:
        text_lower = text.lower()
        if "flight" in text_lower or "机票" in text:
            return "flight_booking"
        if "hotel" in text_lower or "酒店" in text:
            return "hotel_booking"
        if "calendar" in text_lower or "日程" in text or "schedule" in text_lower:
            return "schedule_check"
        return "general"
