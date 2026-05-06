"""场景预设服务层."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.storage.toml_store import TOMLStore


class PresetService:
    """场景预设 CRUD。所有方法均为 async（TOMLStore 异步）。"""

    def __init__(self, store: TOMLStore) -> None:
        """初始化 PresetService."""
        self._store = store

    async def list_all(self) -> list[dict]:
        """返回全部预设."""
        return await self._store.read()

    async def save(self, preset: dict) -> None:
        """追加一个预设."""
        await self._store.append(preset)

    async def delete(self, preset_id: str) -> bool:
        """按 preset_id 删除。找到并删除返回 True，未找到返回 False."""
        all_ = await self._store.read()
        filtered = [p for p in all_ if p.get("id") != preset_id]
        if len(filtered) == len(all_):
            return False
        await self._store.write(filtered)
        return True
