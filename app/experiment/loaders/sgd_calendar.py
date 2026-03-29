"""SGD-Calendar数据集加载模块."""

import logging

from datasets import Dataset, load_dataset

_cache = None


class SGDCalendarLoader:
    """加载SGD-Calendar数据集."""

    def load(self) -> Dataset:
        """加载 SGD-Calendar 数据集."""
        global _cache
        if _cache is None:
            _cache = load_dataset("vidhikatkoria/SGD_Calendar", split="train")

        if len(_cache) > 0:
            sample = _cache[0]
            required_cols = ["context", "text"]
            missing = [c for c in required_cols if c not in sample]
            if missing:
                logging.warning(f"Dataset missing columns: {missing}")

        return _cache

    def get_test_cases(self) -> list[dict]:
        """从数据集提取测试用例."""
        ds = self.load()
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
                            "type": self._infer_type(user_text),
                            "id": f"sgd_{i}",
                        },
                    )
                    if len(test_cases) >= 60:
                        break
            if len(test_cases) >= 60:
                break
        return test_cases

    def _infer_type(self, text: str) -> str:
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
