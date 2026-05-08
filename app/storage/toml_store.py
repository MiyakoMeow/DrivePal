"""TOML文件存储后端，支持列表和字典类型的读写操作."""

import asyncio
import logging
import tomllib
from typing import TYPE_CHECKING, Any, TypeVar, cast

if TYPE_CHECKING:
    from collections.abc import Callable

import aiofiles
import tomli_w

if TYPE_CHECKING:
    from pathlib import Path

T = TypeVar("T")

_LOCK_REGISTRY: dict[str, asyncio.Lock] = {}
_LOCK_REGISTRY_LOCK = asyncio.Lock()

_LIST_WRAPPER_KEY = "_list"

logger = logging.getLogger(__name__)


class AppendError(TypeError):
    """追加操作类型错误."""

    def __init__(self, actual_type: str) -> None:
        """初始化 AppendError."""
        super().__init__(f"list required, got {actual_type}")


class UpdateError(TypeError):
    """更新操作类型错误."""

    def __init__(self, actual_type: str) -> None:
        """初始化 UpdateError."""
        super().__init__(f"dict required, got {actual_type}")


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
        default_factory: Callable[[], T] | None = None,
    ) -> None:
        """初始化TOML存储，指定数据目录和文件名."""
        self.filepath = filename if filename.is_absolute() else data_dir / filename
        if default_factory is None:
            default_factory = cast("Callable[[], T]", dict)
        self.default_factory: Callable[[], T] = default_factory
        self._lock = _get_file_lock(self.filepath)

    async def _ensure_file(self) -> None:
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        if not self.filepath.exists():
            default_data = self.default_factory()
            async with aiofiles.open(self.filepath, "wb") as f:
                if isinstance(default_data, list):
                    await f.write(
                        tomli_w.dumps({_LIST_WRAPPER_KEY: default_data}).encode()
                    )
                else:
                    await f.write(
                        tomli_w.dumps(cast("dict[str, Any]", default_data)).encode()
                    )

    def _clean_for_toml(self, obj: object, _path: str = "") -> object:
        """递归清理对象中的 None 值，转换为空字符串."""
        if isinstance(obj, dict):
            return {k: self._clean_for_toml(v, f"{_path}.{k}") for k, v in obj.items()}
        if isinstance(obj, list):
            return [
                self._clean_for_toml(item, f"{_path}[{i}]")
                for i, item in enumerate(obj)
            ]
        if obj is None:
            logger.warning(
                "None value in TOML output at %s, writing as empty string",
                _path or "root",
            )
            return ""
        return obj

    async def _async_write(self, data: T) -> None:
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        cleaned = self._clean_for_toml(data)
        async with aiofiles.open(self.filepath, "wb") as f:
            if isinstance(cleaned, list):
                await f.write(tomli_w.dumps({_LIST_WRAPPER_KEY: cleaned}).encode())
            else:
                await f.write(tomli_w.dumps(cast("dict[str, Any]", cleaned)).encode())

    async def _read_unsafe(self) -> T:
        """读操作，不获取锁（调用方必须持有锁）."""
        if not self.filepath.exists():
            await self._ensure_file()
        async with aiofiles.open(self.filepath, "rb") as f:
            content = await f.read()
        raw = tomllib.loads(content.decode("utf-8"))
        if _LIST_WRAPPER_KEY in raw and len(raw) == 1:
            return raw[_LIST_WRAPPER_KEY]
        return cast("T", raw)

    async def read(self) -> T:
        """读取TOML文件中的全部数据."""
        async with self._lock:
            return await self._read_unsafe()

    async def write(self, data: T) -> None:
        """写入数据到TOML文件."""
        async with self._lock:
            await self._async_write(data)

    async def append(self, item: object) -> None:
        """向列表类型存储追加一个元素."""
        async with self._lock:
            data = await self._read_unsafe()
            if not isinstance(data, list):
                raise AppendError(type(data).__name__)
            data.append(item)
            await self._async_write(data)

    async def update(self, key: str, value: object) -> None:
        """更新字典类型存储中指定键的值."""
        async with self._lock:
            data = await self._read_unsafe()
            if not isinstance(data, dict):
                raise UpdateError(type(data).__name__)
            data[key] = value
            await self._async_write(data)
