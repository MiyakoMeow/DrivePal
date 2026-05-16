"""数据目录初始化与默认数据填充."""

import logging
import shutil
import tomllib
from pathlib import Path

import tomli_w

from app.config import DATA_DIR, DATA_ROOT, user_data_dir
from app.schemas.context import (
    DriverState,
    DrivingContext,
    GeoLocation,
    ScenarioPreset,
    SpatioTemporalContext,
    TrafficCondition,
)

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


def _seed_demo_presets(user_id: str) -> None:
    """若场景预设列表为空，写入 5 个演示预设。幂等。"""
    u_dir = user_data_dir(user_id)
    sp_fp = u_dir / "scenario_presets.toml"

    # 文件存在且有预设则跳过
    if sp_fp.exists():
        try:
            with sp_fp.open("rb") as f:
                raw = tomllib.loads(f.read().decode("utf-8"))
            if raw.get("_list", []):
                return
        except OSError, ValueError:
            logger.warning(
                "Corrupted scenario_presets.toml for %s, re-seeding", user_id
            )

    presets = [
        ScenarioPreset(
            name="\U0001f17f\ufe0f 停车场准备出发",
            context=DrivingContext(
                driver=DriverState(workload="normal", fatigue_level=0.1),
                spatial=SpatioTemporalContext(
                    current_location=GeoLocation(
                        latitude=39.9042, longitude=116.4074, address="北京市东城区"
                    )
                ),
                scenario="parked",
            ),
        ),
        ScenarioPreset(
            name="\U0001f6e3\ufe0f 高速公路巡航",
            context=DrivingContext(
                driver=DriverState(workload="normal"),
                spatial=SpatioTemporalContext(
                    current_location=GeoLocation(
                        latitude=40.0,
                        longitude=116.3,
                        address="京藏高速",
                        speed_kmh=120,
                    )
                ),
                scenario="highway",
                passengers=["乘客"],
            ),
        ),
        ScenarioPreset(
            name="\U0001f6a6 城市拥堵通勤",
            context=DrivingContext(
                driver=DriverState(fatigue_level=0.4),
                spatial=SpatioTemporalContext(
                    current_location=GeoLocation(
                        latitude=39.92, longitude=116.4, address="北京三环"
                    )
                ),
                traffic=TrafficCondition(
                    congestion_level="congested", estimated_delay_minutes=15
                ),
                scenario="traffic_jam",
            ),
        ),
        ScenarioPreset(
            name="\U0001f634 疲劳驾驶警告",
            context=DrivingContext(
                driver=DriverState(workload="high", fatigue_level=0.8),
                spatial=SpatioTemporalContext(
                    current_location=GeoLocation(
                        latitude=40.05, longitude=116.35, speed_kmh=100
                    )
                ),
                scenario="highway",
            ),
        ),
        ScenarioPreset(
            name="\U0001f399\ufe0f 语音录入",
            context=DrivingContext(
                driver=DriverState(workload="low"),
                spatial=SpatioTemporalContext(
                    current_location=GeoLocation(
                        latitude=39.9042, longitude=116.4074, address="北京"
                    )
                ),
                scenario="parked",
            ),
        ),
    ]

    _write_toml_data(
        sp_fp, {"_list": [p.model_dump(exclude_none=True) for p in presets]}
    )
    logger.info("Seeded %d demo presets for user %s", len(presets), user_id)


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
    _seed_demo_presets("default")
    flag.write_text("1")


if __name__ == "__main__":
    init_storage()
