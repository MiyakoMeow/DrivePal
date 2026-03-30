"""数据目录初始化与默认数据填充."""

import json
from pathlib import Path
from typing import Optional


def get_data_dir() -> Path:
    """获取数据目录路径."""
    return Path(__file__).parent.parent.parent / "data"


def init_storage(data_dir: Optional[Path] = None) -> None:
    """初始化存储目录和数据文件."""
    if data_dir is None:
        data_dir = get_data_dir()
    data_dir.mkdir(exist_ok=True)

    files = {
        "events.json": [],
        "interactions.json": [],
        "contexts.json": {},
        "preferences.json": {"language": "zh-CN"},
        "feedback.json": [],
        "strategies.json": {
            "preferred_time_offset": 15,
            "preferred_method": "visual",
            "reminder_weights": {},
            "ignored_patterns": [],
            "modified_keywords": [],
            "cooldown_periods": {},
        },
        "experiment_results.json": [],
        "memorybank_summaries.json": {"daily_summaries": {}, "overall_summary": ""},
    }

    for filename, default_data in files.items():
        filepath = data_dir / filename
        if not filepath.exists():
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(default_data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    init_storage()
    print("存储初始化完成")
