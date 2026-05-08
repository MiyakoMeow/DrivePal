"""数据目录初始化与默认数据填充."""

from pathlib import Path

import tomli_w


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

    jsonl_files = [
        "events.jsonl",
        "interactions.jsonl",
        "feedback.jsonl",
        "experiment_results.jsonl",
    ]

    dict_files = {
        "contexts.toml": {},
        "preferences.toml": {"language": "zh-CN"},
        "strategies.toml": {
            "preferred_time_offset": 15,
            "preferred_method": "visual",
        },
    }

    for filename in jsonl_files:
        filepath = data_dir / filename
        if not filepath.exists():
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text("", encoding="utf-8")

    for filename, default_data in dict_files.items():
        filepath = data_dir / filename
        if not filepath.exists():
            _write_toml_data(filepath, default_data)


if __name__ == "__main__":
    init_storage()
