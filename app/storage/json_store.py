"""JSON文件存储后端，支持列表和字典类型的读写操作."""

import json
from pathlib import Path
from typing import Any, Callable, TypeVar

T = TypeVar("T")


class JSONStore:
    """基于JSON文件的通用存储引擎."""

    def __init__(
        self,
        data_dir: str,
        filename: str,
        default_factory: Callable[[], T] = lambda: dict(),
    ) -> None:
        """初始化JSON存储，指定数据目录和文件名."""
        self.filepath = Path(data_dir) / filename
        self.default_factory: Callable[[], T] = default_factory
        self._ensure_file()

    def _ensure_file(self) -> None:
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        if not self.filepath.exists():
            self._write(self.default_factory())

    def _write(self, data: T) -> None:
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def read(self) -> T:
        """读取JSON文件中的全部数据."""
        with open(self.filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    def write(self, data: T) -> None:
        """写入数据到JSON文件."""
        self._write(data)

    def append(self, item: Any) -> None:
        """向列表类型存储追加一个元素."""
        data = self.read()
        if not isinstance(data, list):
            raise TypeError(
                f"append() requires list factory, got {type(data).__name__}"
            )
        data.append(item)
        self._write(data)

    def update(self, key: str, value: Any) -> None:
        """更新字典类型存储中指定键的值."""
        data = self.read()
        if not isinstance(data, dict):
            raise TypeError(
                f"update() requires dict factory, got {type(data).__name__}"
            )
        data[key] = value
        self._write(data)
