"""JSONLinesStore 单元测试."""

from typing import TYPE_CHECKING

from app.storage.jsonl_store import JSONLinesStore

if TYPE_CHECKING:
    from pathlib import Path


class TestJSONLinesStore:
    """JSONLinesStore 单元测试."""

    async def test_append_and_read(self, tmp_path: Path) -> None:
        """验证追加写入和读取."""
        s = JSONLinesStore(user_dir=tmp_path, filename="test.jsonl")
        await s.append({"a": 1})
        await s.append({"b": 2})
        items = await s.read_all()
        assert len(items) == 2
        assert items[0] == {"a": 1}
        assert items[1] == {"b": 2}

    async def test_count(self, tmp_path: Path) -> None:
        """验证计数."""
        s = JSONLinesStore(user_dir=tmp_path, filename="test.jsonl")
        await s.append({"x": 1})
        assert await s.count() == 1

    async def test_read_empty_file(self, tmp_path: Path) -> None:
        """验证空文件返回空列表."""
        s = JSONLinesStore(user_dir=tmp_path, filename="test.jsonl")
        items = await s.read_all()
        assert items == []

    async def test_append_empty_object(self, tmp_path: Path) -> None:
        """验证追加空对象."""
        s = JSONLinesStore(user_dir=tmp_path, filename="test.jsonl")
        await s.append({})
        items = await s.read_all()
        assert items == [{}]

    async def test_read_nonexistent_file(self, tmp_path: Path) -> None:
        """验证不存在的文件返回空列表."""
        s = JSONLinesStore(user_dir=tmp_path, filename="nonexistent.jsonl")
        items = await s.read_all()
        assert items == []
        assert await s.count() == 0
