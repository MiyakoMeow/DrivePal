"""Tests for MemoryModule Facade."""

import pytest
from app.memory.memory import MemoryModule


@pytest.fixture
def mm(tmp_path):
    """Provide a MemoryModule instance for testing."""
    return MemoryModule(str(tmp_path))


class TestMemoryModuleFacade:
    """Tests for MemoryModule Facade interface."""

    def test_default_mode_is_memorybank(self, mm):
        """Verify the default mode is memorybank."""
        assert mm._default_mode == "memorybank"

    def test_write_uses_default_mode(self, mm):
        """Verify write uses the default mode store."""
        mm.write({"content": "事件"})
        history = mm.get_history()
        assert len(history) == 1

    def test_search_routes_to_correct_store(self, mm):
        """Verify search routes to the correct store based on mode."""
        mm.write({"content": "测试事件"})
        results = mm.search("测试", mode="keyword")
        assert len(results) == 1

    def test_set_default_mode(self, mm):
        """Verify set_default_mode changes the default mode."""
        mm.set_default_mode("keyword")
        assert mm._default_mode == "keyword"

    def test_write_interaction_calls_memorybank(self, mm):
        """Verify write_interaction calls the memorybank store."""
        interaction_id = mm.write_interaction("提醒我开会", "好的")
        assert isinstance(interaction_id, str)

    def test_write_interaction_falls_back_to_write_for_non_memorybank(self, mm):
        """Verify write_interaction falls back to write for non-memorybank modes."""
        mm.set_default_mode("keyword")
        interaction_id = mm.write_interaction("q", "r")
        assert isinstance(interaction_id, str)
        history = mm.get_history()
        assert len(history) == 1
        assert history[0]["content"] == "r"
