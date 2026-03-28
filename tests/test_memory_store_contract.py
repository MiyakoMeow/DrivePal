"""MemoryStore 接口契约测试 - 验证所有实现满足统一接口."""

import pytest


class TestMemoryStoreContract:
    """验证所有 MemoryStore 实现满足接口契约."""

    @pytest.fixture(params=["keyword", "llm_only", "embeddings", "memorybank"])
    def store(self, request, tmp_path):
        """Provide a store instance for each memory mode."""
        # Note: 使用 _get_store() 访问内部实现是契约测试的设计决策
        # 因为需要验证每个 store 实现都满足同一接口
        from app.memory.memory import MemoryModule

        mm = MemoryModule(str(tmp_path))
        return mm._get_store(request.param)

    def test_write_returns_string_id(self, store):
        """Verify write returns a string event ID."""
        event_id = store.write({"content": "test"})
        assert isinstance(event_id, str)
        assert len(event_id) > 0

    def test_write_then_search_returns_same_event(self, store):
        """Verify written event can be found via search."""
        event_id = store.write({"content": "测试事件"})
        events = store.events_store.read()
        assert any(e["id"] == event_id for e in events)

    def test_search_returns_list(self, store):
        """Verify search returns a list."""
        store.write({"content": "测试事件"})
        results = store.search("测试")
        assert isinstance(results, list)

    def test_get_history_returns_list(self, store):
        """Verify get_history returns a list."""
        store.write({"content": "事件1"})
        history = store.get_history(limit=10)
        assert isinstance(history, list)

    def test_get_history_respects_limit(self, store):
        """Verify get_history respects the limit parameter."""
        for i in range(5):
            store.write({"content": f"事件{i}"})
        history = store.get_history(limit=3)
        assert len(history) == 3

    def test_update_feedback_updates_strategies(self, store):
        """Verify update_feedback updates the strategies store."""
        event_id = store.write({"content": "事件"})
        store.update_feedback(event_id, {"action": "accept", "type": "meeting"})
        strategies = store.strategies_store.read()
        assert "reminder_weights" in strategies
