import json
import sys
from pathlib import Path
from typing import Any, Callable, TypeVar

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

T = TypeVar("T")


class JSONStore:
    def __init__(
        self,
        data_dir: str,
        filename: str,
        default_factory: Callable[[], T] = dict,
    ) -> None:
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
        with open(self.filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    def save(self, data: T) -> None:
        self._write(data)

    def write(self, data: T) -> None:
        self._write(data)

    def append(self, item: Any) -> None:
        with open(self.filepath, "a+", encoding="utf-8") as f:
            if sys.platform == "win32":
                try:
                    msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
                except IOError:
                    pass
            else:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.seek(0)
                content = f.read()
                if content:
                    data = json.loads(content)
                else:
                    data = []
                if not isinstance(data, list):
                    raise TypeError("Can only append to list-type stores")
                data.append(item)
                f.seek(0)
                f.truncate()
                json.dump(data, f, ensure_ascii=False, indent=2)
            finally:
                if sys.platform == "win32":
                    try:
                        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                    except IOError:
                        pass
                else:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def update(self, key: str, value: Any) -> None:
        data = self.read()
        data[key] = value
        self._write(data)
