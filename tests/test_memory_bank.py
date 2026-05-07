"""集成测试：记忆写入 → 检索 → 回放。"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.memory.schemas import MemoryEvent
from app.memory.stores.memory_bank.store import MemoryBankStore


@pytest.fixture
def store():
    """提供 mock embedding 的 MemoryBankStore 实例。"""
    with tempfile.TemporaryDirectory() as tmp:
        emb = AsyncMock(spec=["encode"])
        emb.encode = AsyncMock(return_value=[0.1] * 1536)
        s = MemoryBankStore(Path(tmp), embedding_model=emb)
        yield s


@pytest.mark.asyncio
async def test_write_and_search_roundtrip(store):
    """验证写入交互后可搜索到结果。"""
    await store.write_interaction(
        "what is Gary's seat preference", "Gary likes seat at 30%"
    )
    results = await store.search("Gary seat", top_k=5)
    assert len(results) >= 1
    content = results[0].event.get("content", "")
    assert "Gary" in content or "seat" in content


@pytest.mark.asyncio
async def test_write_multiple_and_search(store):
    """验证多条写入后可按主题搜索。"""
    await store.write_interaction("set temperature to 22", "temperature set to 22")
    await store.write_interaction("play jazz music", "playing jazz")
    await store.write_interaction("navigate to airport", "navigating to airport")
    results = await store.search("music", top_k=5)
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_search_empty_store(store):
    """验证空存储搜索返回空列表。"""
    results = await store.search("anything", top_k=5)
    assert results == []


@pytest.mark.asyncio
async def test_write_paired_vectorization(store):
    """验证多行内容按 2 行配对入库，而非每行独立。"""
    lines = [
        "Gary: set seat to 30%",
        "AI: seat set to 30%",
        "Gary: set temperature to 22",
        "AI: temperature set to 22",
        "Gary: lone message",
    ]
    content = "\n".join(lines)
    await store.write(MemoryEvent(content=content))
    meta = store._index.get_metadata()
    # 5 行 → 2 个配对 + 1 个单行 = 3 条向量
    assert len(meta) == 3, f"expected 3 metadata entries, got {len(meta)}"
    # 验证配对格式
    paired_text = meta[0].get("text", "")
    assert "[|Gary|]" in paired_text
    assert "[|AI|]" in paired_text
    assert "set seat to 30%" in paired_text
    assert "seat set to 30%" in paired_text
    # 验证单行独立
    lone_text = meta[-1].get("text", "")
    assert "lone message" in lone_text
