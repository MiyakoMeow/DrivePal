"""MemoryBankStore 测试 - 仅存储级别测试."""

from unittest.mock import MagicMock

import pytest

from app.memory.stores.memory_bank import MemoryBankStore
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def mock_chat_model() -> MagicMock:
    """创建 mock chat model."""
    chat = MagicMock()
    chat.generate.return_value = "测试摘要"
    return chat


@pytest.fixture
def store(tmp_path: Path) -> MemoryBankStore:
    """创建用于测试的 MemoryBankStore."""
    return MemoryBankStore(tmp_path)


@pytest.fixture
def store_with_llm(tmp_path: Path, mock_chat_model: MagicMock) -> MemoryBankStore:
    """创建带 chat model 的 MemoryBankStore."""
    return MemoryBankStore(tmp_path, chat_model=mock_chat_model)


class TestWriteInteraction:
    """write_interaction 功能测试."""

    async def test_write_interaction_creates_record(
        self, store: MemoryBankStore
    ) -> None:
        """验证 write_interaction 创建交互记录."""
        interaction_id = await store.write_interaction("提醒我开会", "好的")
        assert isinstance(interaction_id, str)
        interactions = await store.interactions_store.read()
        stored_ids = [i["id"] for i in interactions]
        assert interaction_id in stored_ids, (
            f"returned id {interaction_id} not found in stored {stored_ids}"
        )

    async def test_write_interaction_aggregates_similar(
        self, store: MemoryBankStore
    ) -> None:
        """验证相似交互被聚合."""
        await store.write_interaction("提醒我明天上午开会", "好的")
        await store.write_interaction("明天下午也有会议", "已更新")
        events = await store.events_store.read()
        assert len(events) == 1
        assert len(events[0]["interaction_ids"]) == 2
