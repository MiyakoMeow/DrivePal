"""PresetService 单元测试."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.preset_service import PresetService


@pytest.mark.asyncio
async def test_list_all_empty():
    """空存储返回空列表."""
    store = MagicMock()
    store.read = AsyncMock(return_value=[])
    svc = PresetService(store)
    result = await svc.list_all()
    assert result == []


@pytest.mark.asyncio
async def test_list_all_returns_raw():
    """返回原始预设数据列表."""
    store = MagicMock()
    raw = [{"id": "1", "name": "高速", "context": {}, "created_at": "2024-01-01"}]
    store.read = AsyncMock(return_value=raw)
    svc = PresetService(store)
    result = await svc.list_all()
    assert len(result) == 1
    assert result[0]["name"] == "高速"


@pytest.mark.asyncio
async def test_save_appends_preset():
    """保存操作委托给 store.append."""
    store = MagicMock()
    store.read = AsyncMock(return_value=[])
    store.append = AsyncMock()
    svc = PresetService(store)
    preset_dict = {
        "id": "abc",
        "name": "new",
        "context": {},
        "created_at": "2024-01-01",
    }
    await svc.save(preset_dict)
    store.append.assert_called_once_with(preset_dict)


@pytest.mark.asyncio
async def test_delete_by_id():
    """按 ID 删除成功返回 True."""
    store = MagicMock()
    store.read = AsyncMock(
        return_value=[
            {"id": "a", "name": "A"},
            {"id": "b", "name": "B"},
        ]
    )
    store.write = AsyncMock()
    svc = PresetService(store)
    result = await svc.delete("b")
    assert result is True
    store.write.assert_called_once_with([{"id": "a", "name": "A"}])


@pytest.mark.asyncio
async def test_delete_nonexistent_returns_false():
    """删除不存在的 ID 返回 False."""
    store = MagicMock()
    store.read = AsyncMock(
        return_value=[
            {"id": "a", "name": "A"},
        ]
    )
    svc = PresetService(store)
    result = await svc.delete("nonexistent")
    assert result is False
