"""Tests for MemoryModule Facade."""

from pathlib import Path

import pytest
from app.memory.memory import MemoryModule
from app.memory.schemas import MemoryEvent, SearchResult
from app.memory.types import MemoryMode
from tests.conftest import SKIP_IF_NO_LLM


@pytest.fixture
def mm(tmp_path: Path) -> MemoryModule:
    """提供一个 MemoryModule 实例用于测试."""
    return MemoryModule(str(tmp_path))


@SKIP_IF_NO_LLM
class TestMemoryModuleFacade:
    """MemoryModule Facade 接口测试."""

    def test_default_mode_is_memory_bank(self, mm: MemoryModule) -> None:
        """验证默认模式为 memory_bank."""
        assert mm._default_mode == "memory_bank"

    def test_write_uses_default_mode(self, mm: MemoryModule) -> None:
        """验证 write 使用默认模式存储."""
        mm.write(MemoryEvent(content="事件"))
        history = mm.get_history()
        assert len(history) == 1
        assert isinstance(history[0], MemoryEvent)

    def test_search_routes_to_correct_store(self, mm: MemoryModule) -> None:
        """验证 search 路由到正确的存储后端."""
        mm.write(MemoryEvent(content="测试事件"))
        results = mm.search("测试", mode=MemoryMode.KEYWORD)
        assert len(results) == 1
        assert isinstance(results[0], SearchResult)

    def test_set_default_mode(self, mm: MemoryModule) -> None:
        """验证 set_default_mode 正确切换默认模式."""
        mm.set_default_mode(MemoryMode.KEYWORD)
        assert mm._default_mode == "keyword"

    def test_write_interaction_calls_memory_bank(self, mm: MemoryModule) -> None:
        """验证 write_interaction 在 memory_bank 模式下返回字符串 ID."""
        interaction_id = mm.write_interaction("提醒我开会", "好的")
        assert isinstance(interaction_id, str)

    def test_write_interaction_for_non_memory_bank(self, mm: MemoryModule) -> None:
        """验证非 memory_bank 模式下 write_interaction 正确回退."""
        mm.set_default_mode(MemoryMode.KEYWORD)
        interaction_id = mm.write_interaction("查询内容", "响应内容")
        assert isinstance(interaction_id, str)
        history = mm.get_history()
        assert len(history) == 1
        assert history[0].content == "查询内容"
        assert history[0].description == "响应内容"

    def test_search_returns_search_result_objects(self, mm: MemoryModule) -> None:
        """验证 search 返回 SearchResult 对象列表."""
        mm.write(MemoryEvent(content="特殊关键词事件"))
        results = mm.search("特殊关键词", mode=MemoryMode.KEYWORD)
        assert all(isinstance(r, SearchResult) for r in results)
        pub = results[0].to_public()
        assert "score" not in pub

    def test_get_history_returns_memory_event_objects(self, mm: MemoryModule) -> None:
        """验证 get_history 返回 MemoryEvent 对象列表."""
        mm.write(MemoryEvent(content="事件"))
        history = mm.get_history()
        assert all(isinstance(e, MemoryEvent) for e in history)
