"""数据目录初始化与默认数据填充."""

import logging
import shutil
from pathlib import Path

import tomli_w

from app.config import DATA_DIR, DATA_ROOT, user_data_dir

logger = logging.getLogger(__name__)

_MIGRATED_FLAG = ".migrated_flag"


def _write_toml_data(filepath: Path, data: dict) -> None:
    """写入 TOML 数据到文件."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with filepath.open("wb") as f:
        tomli_w.dump(data, f)


def _migrate_text_files(default_dir: Path, old_root: Path) -> bool:
    """迁移平铺 jsonl/toml 文件到 default_dir。返回是否有文件迁移。"""
    jsonl_files = [
        "events.jsonl",
        "interactions.jsonl",
        "feedback.jsonl",
    ]
    toml_files = [
        "contexts.toml",
        "preferences.toml",
        "strategies.toml",
        "scenario_presets.toml",
    ]
    all_files = jsonl_files + toml_files
    if not any((old_root / f).exists() for f in all_files):
        return False
    default_dir.mkdir(parents=True, exist_ok=True)
    for f in all_files:
        src = old_root / f
        if src.exists():
            shutil.move(str(src), str(default_dir / f))
    return True


def _migrate_memorybank(default_dir: Path, old_root: Path) -> None:
    """迁移 data/memorybank/ 和 data/user_*/ 到 data/users/ 结构。"""
    # 检查 data/memorybank/ 子目录（如果有的话）
    mb_dir = old_root / "memorybank"
    if mb_dir.exists():
        user_dirs = [
            d for d in mb_dir.iterdir() if d.is_dir() and d.name.startswith("user_")
        ]
        if user_dirs:
            for ud in user_dirs:
                user_id = ud.name[5:]
                target = user_data_dir(user_id) / "memorybank"
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(ud), str(target))
            if not any(mb_dir.iterdir()):
                mb_dir.rmdir()
        else:
            target = default_dir / "memorybank"
            if not target.exists():
                shutil.move(str(mb_dir), str(target))

    # 检查 data/user_*/ 平铺目录（store 旧路径 data/user_{id}/）
    for entry in old_root.iterdir():
        if entry.is_dir() and entry.name.startswith("user_"):
            user_id = entry.name[5:]  # 去掉 "user_" 前缀
            target_root = user_data_dir(user_id)
            target_root.parent.mkdir(parents=True, exist_ok=True)
            if not target_root.exists():
                shutil.move(str(entry), str(target_root))


def _migrate_legacy() -> bool:
    """将平铺 data/ 下文件与目录迁移至 data/users/default/。幂等。"""
    default_dir = user_data_dir("default")
    if default_dir.exists():
        return False
    old_root = DATA_ROOT
    moved_files = _migrate_text_files(default_dir, old_root)
    _migrate_memorybank(default_dir, old_root)
    return moved_files


def init_user_dir(user_id: str) -> Path:
    """初始化指定用户的完整目录结构。"""
    u_dir = user_data_dir(user_id)
    u_dir.mkdir(parents=True, exist_ok=True)

    jsonl_files = [
        "events.jsonl",
        "interactions.jsonl",
        "feedback.jsonl",
        "feedback_log.jsonl",
    ]

    for fname in jsonl_files:
        fp = u_dir / fname
        if not fp.exists():
            fp.write_text("", encoding="utf-8")

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
    }

    for fname, default_data in dict_files.items():
        fp = u_dir / fname
        if not fp.exists():
            _write_toml_data(fp, default_data)

    # scenario_presets.toml — 用 _list 包裹的列表
    sp_fp = u_dir / "scenario_presets.toml"
    if not sp_fp.exists():
        _write_toml_data(sp_fp, {"_list": []})

    return u_dir


def init_storage(data_dir: Path | None = None) -> None:
    """初始化数据目录。存在标记时跳过迁移。"""
    root = data_dir or DATA_DIR
    root.mkdir(parents=True, exist_ok=True)
    flag = root / _MIGRATED_FLAG
    if flag.exists():
        logger.debug("Migration already completed, skipping")
        return
    _migrate_legacy()
    init_user_dir("default")
    flag.write_text("1")


if __name__ == "__main__":
    init_storage()
