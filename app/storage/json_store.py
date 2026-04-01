"""JSON文件存储后端，支持列表和字典类型的读写操作."""

import asyncio
import json
from pathlib import Path
from typing import Any, Callable, TypeVar

import aiofiles

T = TypeVar("T")

_LOCK_REGISTRY: dict[str, asyncio.Lock] = {}
_LOCK_REGISTRY_LOCK = asyncio.Lock()


def _get_file_lock(filepath: Path) -> asyncio.Lock:
    """获取文件路径对应的锁，实现跨实例共享."""
    key = str(filepath.resolve())
    return _LOCK_REGISTRY.setdefault(key, asyncio.Lock())


class JSONStore:
    """基于JSON文件的通用存储引擎."""

    def __init__(
        self,
        data_dir: Path,
        filename: Path,
        default_factory: Callable[[], T] = lambda: dict(),
    ) -> None:
        """初始化JSON存储，指定数据目录和文件名."""
        self.filepath = filename if filename.is_absolute() else data_dir / filename
        self.default_factory: Callable[[], T] = default_factory
        self._lock = _get_file_lock(self.filepath)

    def _ensure_file(self) -> None:
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        if not self.filepath.exists():
            with self.filepath.open("w", encoding="utf-8") as f:
                json.dump(self.default_factory(), f, ensure_ascii=False, indent=2)

    async def _async_write(self, data: T) -> None:
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(self.filepath, "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, ensure_ascii=False, indent=2))

    async def _read_unsafe(self) -> T:
        """读操作，不获取锁（调用方必须持有锁）."""
        if not await asyncio.to_thread(self.filepath.exists):
            await asyncio.to_thread(self._ensure_file)
        async with aiofiles.open(self.filepath, "r", encoding="utf-8") as f:
            content = await f.read()
        return json.loads(content)

    async def read(self) -> T:
        """读取JSON文件中的全部数据."""
        async with self._lock:
            return await self._read_unsafe()

    async def write(self, data: T) -> None:
        """写入数据到JSON文件."""
        async with self._lock:
            await self._async_write(data)

    async def append(self, item: Any) -> None:  # noqa: ANN401
        """向列表类型存储追加一个元素."""
        async with self._lock:
            data = await self._read_unsafe()
            if not isinstance(data, list):
                raise TypeError(
                    f"append() requires list factory, got {type(data).__name__}"
                )
            data.append(item)
            await self._async_write(data)

    async def update(self, key: str, value: Any) -> None:  # noqa: ANN401
        """更新字典类型存储中指定键的值."""
        async with self._lock:
            data = await self._read_unsafe()
            if not isinstance(data, dict):
                raise TypeError(
                    f"update() requires dict factory, got {type(data).__name__}"
                )
            data[key] = value
            await self._async_write(data)
