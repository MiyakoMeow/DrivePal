"""Tests for MemoryModule Facade."""

import pytest
from app.memory.memory import MemoryModule


@pytest.fixture
def mm(tmp_path):
    return MemoryModule(str(tmp_path))


class TestMemoryModuleFacade:
    def test_default_mode_is_memorybank(self, mm):
        assert mm._default_mode == "memorybank"

    def test_write_uses_default_mode(self, mm):
        mm.write({"content": "事件"})
        history = mm.get_history()
        assert len(history) == 1

    def test_search_routes_to_correct_store(self, mm):
        mm.write({"content": "测试事件"})
        results = mm.search("测试", mode="keyword")
        assert len(results) == 1

    def test_set_default_mode(self, mm):
        mm.set_default_mode("keyword")
        assert mm._default_mode == "keyword"

    def test_write_interaction_calls_memorybank(self, mm):
        interaction_id = mm.write_interaction("提醒我开会", "好的")
        assert isinstance(interaction_id, str)

    def test_write_interaction_raises_for_non_memorybank(self, mm):
        mm.set_default_mode("keyword")
        with pytest.raises(NotImplementedError):
            mm.write_interaction("q", "r")
