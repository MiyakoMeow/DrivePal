"""JSON Lines 追加写存储，支持异步读写."""

import json
import logging
from typing import TYPE_CHECKING, Any

import aiofiles

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class JSONLinesStore:
    """JSON Lines 文件存储，追加写 O(1)，进程安全（O_APPEND）."""

    def __init__(self, user_dir: Path, filename: str) -> None:
        """初始化存储实例，指定用户目录和文件名."""
        self.filepath = user_dir / filename

    async def append(self, obj: dict[str, Any]) -> None:
        """追加写入一条 JSON 对象（新行）."""
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(obj, ensure_ascii=False) + "\n"
        async with aiofiles.open(self.filepath, "a", encoding="utf-8") as f:
            await f.write(line)

    async def read_all(self) -> list[dict[str, Any]]:
        """读取所有行，每行解析为 dict。文件不存在或为空返回 []."""
        if not self.filepath.exists():
            return []
        result: list[dict[str, Any]] = []
        async with aiofiles.open(self.filepath, encoding="utf-8") as f:
            async for raw_line in f:
                stripped = raw_line.strip()
                if stripped:
                    try:
                        result.append(json.loads(stripped))
                    except json.JSONDecodeError as e:
                        logger.warning("Skipping invalid JSON line: %s", e)
        return result

    async def count(self) -> int:
        """返回文件行数（近似于记录数）."""
        if not self.filepath.exists():
            return 0
        count = 0
        async with aiofiles.open(self.filepath, encoding="utf-8") as f:
            async for _ in f:
                count += 1
        return count
