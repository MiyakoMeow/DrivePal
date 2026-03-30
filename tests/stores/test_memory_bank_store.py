"""MemoryBankStore 测试 - 仅存储级别测试."""

from unittest.mock import MagicMock

import pytest

from app.memory.stores.memory_bank_store import MemoryBankStore


@pytest.fixture
def mock_chat_model() -> MagicMock:
    """Create a mock chat model."""
    chat = MagicMock()
    chat.generate.return_value = "测试摘要"
    return chat


@pytest.fixture
def store(tmp_path: str) -> MemoryBankStore:
    """Create a MemoryBankStore for testing."""
    return MemoryBankStore(str(tmp_path))


@pytest.fixture
def store_with_llm(tmp_path: str, mock_chat_model: MagicMock) -> MemoryBankStore:
    """Create a MemoryBankStore with chat model."""
    return MemoryBankStore(str(tmp_path), chat_model=mock_chat_model)


class TestWriteInteraction:
    """Tests for write_interaction functionality."""

    def test_write_interaction_creates_record(self, store: MemoryBankStore) -> None:
        """Test that write_interaction creates an interaction record."""
        interaction_id = store.write_interaction("提醒我开会", "好的")
        assert isinstance(interaction_id, str)
        interactions = store.interactions_store.read()
        stored_ids = [i["id"] for i in interactions]
        assert interaction_id in stored_ids, (
            f"returned id {interaction_id} not found in stored {stored_ids}"
        )

    def test_write_interaction_aggregates_similar(self, store: MemoryBankStore) -> None:
        """Test that similar interactions are aggregated."""
        store.write_interaction("提醒我明天上午开会", "好的")
        store.write_interaction("明天下午也有会议", "已更新")
        events = store.events_store.read()
        assert len(events) == 1
        assert len(events[0]["interaction_ids"]) == 2
