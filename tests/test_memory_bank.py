"""集成测试：记忆写入 → 检索 → 回放。"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.memory.enricher import OverallContextEnricher
from app.memory.stores.memory_bank.faiss_index import FaissIndex
from app.memory.stores.memory_bank.forget import ForgettingCurve
from app.memory.stores.memory_bank.retrieval import RetrievalPipeline
from app.memory.stores.memory_bank.store import MemoryBankStore


@pytest.fixture
def store():
    """提供 mock embedding 的 MemoryBankStore 实例。"""
    with tempfile.TemporaryDirectory() as tmp:
        emb = AsyncMock(spec=["encode"])
        emb.encode = AsyncMock(return_value=[0.1] * 1536)
        index = FaissIndex(Path(tmp))
        retrieval = RetrievalPipeline(index, emb)
        forgetting = ForgettingCurve()
        enricher = OverallContextEnricher()
        s = MemoryBankStore(
            index=index,
            retrieval=retrieval,
            embedding_model=emb,
            enricher=enricher,
            forgetting=forgetting,
        )
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
