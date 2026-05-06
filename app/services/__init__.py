"""服务层模块."""

from pathlib import Path

from app.config import DATA_DIR
from app.services.preset_service import PresetService
from app.storage.toml_store import TOMLStore


def create_preset_service() -> PresetService:
    """创建 PresetService 实例。"""
    store = TOMLStore(DATA_DIR, Path("scenario_presets.toml"), list)
    return PresetService(store)
