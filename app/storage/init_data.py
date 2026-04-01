"""数据目录初始化与默认数据填充."""

from pathlib import Path

import tomli_w

from app.storage.toml_store import _LIST_WRAPPER_KEY


def get_data_dir() -> Path:
    """获取数据目录路径."""
    return Path(__file__).parent.parent.parent / "data"


def _write_toml_data(filepath: Path, data: dict) -> None:
    """写入 TOML 数据到文件."""
    with filepath.open("wb") as f:
        tomli_w.dump(data, f)


def init_storage(data_dir: Path | None = None) -> None:
    """初始化存储目录和数据文件."""
    if data_dir is None:
        data_dir = get_data_dir()
    data_dir.mkdir(exist_ok=True)

    list_files = {
        "events.toml": [],
        "interactions.toml": [],
        "feedback.toml": [],
        "experiment_results.toml": [],
    }

    dict_files = {
        "contexts.toml": {},
        "preferences.toml": {"language": "zh-CN"},
        "strategies.toml": {
            "preferred_time_offset": 15,
            "preferred_method": "visual",
            "reminder_weights": {},
            "ignored_patterns": [],
            "modified_keywords": [],
            "cooldown_periods": {},
        },
        "memorybank_summaries.toml": {"daily_summaries": {}, "overall_summary": ""},
    }

    for filename, default_data in list_files.items():
        filepath = data_dir / filename
        if not filepath.exists():
            _write_toml_data(filepath, {_LIST_WRAPPER_KEY: default_data})

    for filename, default_data in dict_files.items():
        filepath = data_dir / filename
        if not filepath.exists():
            _write_toml_data(filepath, default_data)


if __name__ == "__main__":
    init_storage()
    print("存储初始化完成")
