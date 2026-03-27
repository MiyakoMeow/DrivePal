"""SGD-Calendar数据集加载模块."""

from datasets import load_dataset, Dataset
from typing import List, Dict


class SGDCalendarLoader:

    """加载SGD-Calendar数据集."""

    _cache = None

    @classmethod
    def load(cls) -> Dataset:
        """加载SGD-Calendar数据集."""
        if cls._cache is None:
            cls._cache = load_dataset("vidhikatkoria/SGD_Calendar", split="train")

        if len(cls._cache) > 0:
            sample = cls._cache[0]
            required_cols = ["context", "text"]
            missing = [c for c in required_cols if c not in sample]
            if missing:
                import logging

                logging.warning(f"Dataset missing columns: {missing}")

        return cls._cache

    @classmethod
    def get_test_cases(cls) -> List[Dict]:
        """获取SGD-Calendar测试用例列表."""
        ds = cls.load()
        test_cases = []
        for i, row in enumerate(ds):
            text = row.get("context", "")
            if "User:" in text:
                user_turns = [
                    t.strip()
                    for t in text.split("<SEP>")
                    if t.strip().startswith("User:")
                ]
                for turn in user_turns:
                    user_text = turn.replace("User:", "").strip()
                    test_cases.append(
                        {
                            "input": user_text,
                            "type": cls._infer_type(user_text),
                            "id": f"sgd_{i}",
                        }
                    )
                    if len(test_cases) >= 60:
                        break
            if len(test_cases) >= 60:
                break
        return test_cases

    @classmethod
    def _infer_type(cls, text: str) -> str:
        text_lower = text.lower()
        if any(
            k in text_lower
            for k in ["schedule", "calendar", "available", "free", "时间", "日程"]
        ):
            return "schedule_check"
        if any(
            k in text_lower for k in ["add", "create", "new", "book", "预约", "添加"]
        ):
            return "event_add"
        return "general"


def get_sgd_calendar_test_cases() -> List[Dict]:
    """获取SGD-Calendar测试用例."""
    return SGDCalendarLoader.get_test_cases()


if __name__ == "__main__":
    cases = get_sgd_calendar_test_cases()
    print(f"SGD-Calendar测试用例数: {len(cases)}")
    for c in cases[:3]:
        print(f"  - {c}")
