"""TOML文件存储后端，支持列表和字典类型的读写操作."""

import asyncio
import tomllib
from typing import Any, Callable, TypeVar, TYPE_CHECKING

import aiofiles
import tomli_w

if TYPE_CHECKING:
    from pathlib import Path

T = TypeVar("T")

_LOCK_REGISTRY: dict[str, asyncio.Lock] = {}

_LIST_WRAPPER_KEY = "_list"


def _get_file_lock(filepath: Path) -> asyncio.Lock:
    """获取文件路径对应的锁，实现跨实例共享."""
    key = str(filepath.resolve())
    return _LOCK_REGISTRY.setdefault(key, asyncio.Lock())


class TOMLStore:
    """基于TOML文件的通用存储引擎."""

    def __init__(
        self,
        data_dir: Path,
        filename: Path,
        default_factory: Callable[[], T] = lambda: dict(),
    ) -> None:
        """初始化TOML存储，指定数据目录和文件名."""
        self.filepath = filename if filename.is_absolute() else data_dir / filename
        self.default_factory: Callable[[], T] = default_factory
        self._lock = _get_file_lock(self.filepath)

    def _ensure_file(self) -> None:
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        if not self.filepath.exists():
            default_data = self.default_factory()
            with self.filepath.open("wb") as f:
                if isinstance(default_data, list):
                    tomli_w.dump({_LIST_WRAPPER_KEY: default_data}, f)
                else:
                    tomli_w.dump(default_data, f)  # type: ignore

    def _clean_for_toml(self, obj: object) -> object:
        """递归清理对象中的 None 值，转换为空字符串."""
        if isinstance(obj, dict):
            return {k: self._clean_for_toml(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._clean_for_toml(item) for item in obj]
        elif obj is None:
            return ""
        return obj

    async def _async_write(self, data: T) -> None:
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        cleaned = self._clean_for_toml(data)
        async with aiofiles.open(self.filepath, "wb") as f:
            if isinstance(cleaned, list):
                await f.write(tomli_w.dumps({_LIST_WRAPPER_KEY: cleaned}).encode())
            else:
                await f.write(tomli_w.dumps(cleaned).encode())  # type: ignore

    async def _read_unsafe(self) -> T:
        """读操作，不获取锁（调用方必须持有锁）."""
        if not await asyncio.to_thread(self.filepath.exists):
            await asyncio.to_thread(self._ensure_file)
        async with aiofiles.open(self.filepath, "rb") as f:
            content = await f.read()
        raw = tomllib.loads(content.decode("utf-8"))
        if _LIST_WRAPPER_KEY in raw and len(raw) == 1:
            return raw[_LIST_WRAPPER_KEY]
        return raw  # type: ignore

    async def read(self) -> T:
        """读取TOML文件中的全部数据."""
        async with self._lock:
            return await self._read_unsafe()

    async def write(self, data: T) -> None:
        """写入数据到TOML文件."""
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
