"""语音转录到 MemoryBank 集成测试."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from app.memory.memory import MemoryModule
from app.memory.schemas import EVENT_TYPE_PASSIVE_VOICE, MemoryEvent, SearchResult

if TYPE_CHECKING:
    from pathlib import Path

TEST_USER = "test_voice_memory"
TEST_TEXT = "明天下午3点加油"
TEST_QUERY = "加油"


def _make_embedding_mock(dim: int = 1536):
    """构造返回常向量的 mock embedding 模型。"""
    emb = AsyncMock(spec=["encode", "batch_encode"])
    emb.encode = AsyncMock(return_value=[0.1] * dim)
    emb.batch_encode = AsyncMock(return_value=[[0.1] * dim])
    return emb


def _make_chat_mock() -> AsyncMock:
    """构造 mock 聊天模型，generate 返回空字符串以静默降级 finalize。"""
    chat = AsyncMock()
    chat.generate = AsyncMock(return_value="")
    return chat


async def test_voice_transcription_to_memorybank_retrieval(tmp_path: Path):
    """Given 语音转录文本, When 存入MemoryBank后搜索, Then 搜索结果包含该事件。"""
    memory = MemoryModule(
        tmp_path,
        embedding_model=_make_embedding_mock(),
        chat_model=_make_chat_mock(),
    )

    event = MemoryEvent(
        content=TEST_TEXT,
        type=EVENT_TYPE_PASSIVE_VOICE,
    )

    try:
        event_id = await memory.write(event, user_id=TEST_USER)
        assert event_id, "write 应返回非空 event_id"

        results = await memory.search(TEST_QUERY, top_k=5, user_id=TEST_USER)
        assert len(results) >= 1, "搜索结果不应为空"

        found = any(TEST_TEXT in r.event.get("content", "") for r in results)
        assert found, f"搜索结果应包含原文'{TEST_TEXT}'"

        for r in results:
            assert isinstance(r, SearchResult)
    finally:
        await memory.close()
