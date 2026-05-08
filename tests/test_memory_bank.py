"""集成测试：记忆写入 → 检索 → 回放（多用户版）。"""

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from app.memory.memory_bank.store import MemoryBankStore
from app.memory.schemas import MemoryEvent


@pytest.fixture
def store(tmp_path: Path) -> MemoryBankStore:
    emb = AsyncMock(spec=["encode", "batch_encode"])
    emb.encode = AsyncMock(return_value=[0.1] * 1536)
    emb.batch_encode = AsyncMock(
        side_effect=lambda texts: [[0.1] * 1536 for _ in texts]
    )
    chat = AsyncMock(spec=["generate"])
    chat.generate = AsyncMock(return_value="summary")
    return MemoryBankStore(tmp_path, emb, chat)


@pytest.mark.asyncio
async def test_write_and_search_roundtrip(store: MemoryBankStore) -> None:
    """验证写入交互后可搜索到结果。"""
    await store.write_interaction(
        "user_1", "what is Gary's seat preference", "Gary likes seat at 30%"
    )
    results = await store.search("user_1", "Gary seat", top_k=5)
    assert len(results) >= 1
    content = results[0].event.get("content", "")
    assert "Gary" in content or "seat" in content


@pytest.mark.asyncio
async def test_write_multiple_and_search(store: MemoryBankStore) -> None:
    """验证多条写入后可按主题搜索。"""
    await store.write_interaction(
        "user_1", "set temperature to 22", "temperature set to 22"
    )
    await store.write_interaction("user_1", "play jazz music", "playing jazz")
    await store.write_interaction(
        "user_1", "navigate to airport", "navigating to airport"
    )
    results = await store.search("user_1", "music", top_k=5)
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_search_empty_store(store: MemoryBankStore) -> None:
    """验证空存储搜索返回空列表。"""
    results = await store.search("user_1", "anything", top_k=5)
    assert results == []


@pytest.mark.asyncio
async def test_write_paired_vectorization(store: MemoryBankStore) -> None:
    """验证多行内容按 2 行配对入库，而非每行独立。"""
    lines = [
        "Gary: set seat to 30%",
        "AI: seat set to 30%",
        "Gary: set temperature to 22",
        "AI: temperature set to 22",
        "Gary: lone message",
    ]
    content = "\n".join(lines)
    await store.write("user_1", MemoryEvent(content=content))
    meta = store._index_manager.get_metadata("user_1")
    paired_texts = [
        m.get("text", "")
        for m in meta
        if "[|Gary|]" in m.get("text", "") and "[|AI|]" in m.get("text", "")
    ]
    assert len(paired_texts) >= 1, "expected >=1 paired entry"
    pt = paired_texts[0]
    assert "set seat to 30%" in pt
    assert "seat set to 30%" in pt
    lone_count = sum(1 for m in meta if "lone message" in m.get("text", ""))
    assert lone_count >= 1, f"expected >=1 lone entry, got {lone_count}"
