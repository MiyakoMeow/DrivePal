import json
from pathlib import Path
from typing import Any, Callable, TypeVar

T = TypeVar("T")


class JSONStore:
    def __init__(
        self,
        data_dir: str,
        filename: str,
        default_factory: Callable[[], T] = dict,  # type: ignore[assignment]
    ) -> None:
        self.filepath = Path(data_dir) / filename
        self.default_factory: Callable[[], T] = default_factory  # type: ignore[assignment]
        self._ensure_file()

    def _ensure_file(self) -> None:
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        if not self.filepath.exists():
            self._write(self.default_factory())

    def _write(self, data: T) -> None:
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def read(self) -> T:
        with open(self.filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    def save(self, data: T) -> None:
        self._write(data)

    def write(self, data: T) -> None:  # type: ignore[no-untyped-def]
        self._write(data)

    def append(self, item: Any) -> None:
        data = self.read()
        if isinstance(data, list):
            data.append(item)
            self._write(data)
        else:
            raise TypeError("Can only append to list-type stores")

    def update(self, key: str, value: Any) -> None:
        data = self.read()
        data[key] = value
        self._write(data)
