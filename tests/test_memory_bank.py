"""集成测试：记忆写入 → 检索 → 回放。"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.memory.memory_bank.config import MemoryBankConfig
from app.memory.memory_bank.store import MemoryBankStore
from app.memory.schemas import MemoryEvent


@pytest.fixture
def store():
    """提供 mock embedding 的 MemoryBankStore 实例。"""
    with tempfile.TemporaryDirectory() as tmp:
        emb = AsyncMock(spec=["encode", "batch_encode"])
        emb.encode = AsyncMock(return_value=[0.1] * 1536)

        async def _batch_encode(texts: list[str]) -> list[list[float]]:
            return [[0.1] * 1536 for _ in texts]

        emb.batch_encode = AsyncMock(side_effect=_batch_encode)
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
    # 验证配对格式（含双方说话人标记）
    paired_texts = [
        m.get("text", "")
        for m in meta
        if "[|Gary|]" in m.get("text", "") and "[|AI|]" in m.get("text", "")
    ]
    assert len(paired_texts) >= 1, "expected >=1 paired entry"
    pt = paired_texts[0]
    assert "set seat to 30%" in pt
    assert "seat set to 30%" in pt
    # 验证单行独立
    lone_count = sum(1 for m in meta if "lone message" in m.get("text", ""))
    assert lone_count >= 1, f"expected >=1 lone entry, got {lone_count}"


def test_max_memory_strength_default():
    """验证 max_memory_strength 默认值为 10。"""
    config = MemoryBankConfig()
    assert config.max_memory_strength == 10


def test_max_memory_strength_env(monkeypatch):
    """验证环境变量 MEMORYBANK_MAX_MEMORY_STRENGTH 生效。"""
    monkeypatch.setenv("MEMORYBANK_MAX_MEMORY_STRENGTH", "5")
    config = MemoryBankConfig()
    assert config.max_memory_strength == 5


def test_max_memory_strength_negative_guarded():
    """验证 max_memory_strength=0 被守卫回退为 10。"""
    config = MemoryBankConfig(max_memory_strength=0)
    assert config.max_memory_strength == 10


def test_retrieval_alpha_default():
    """验证 retrieval_alpha 默认值为 0.7。"""
    config = MemoryBankConfig()
    assert config.retrieval_alpha == 0.7


def test_retrieval_alpha_out_of_range_guarded():
    """验证 retrieval_alpha=1.5 被守卫回退为 0.7。"""
    config = MemoryBankConfig(retrieval_alpha=1.5)
    assert config.retrieval_alpha == 0.7


def test_bm25_fallback_defaults():
    """验证 BM25 回退开关默认启用、阈值默认 0.5。"""
    config = MemoryBankConfig()
    assert config.bm25_fallback_enabled is True
    assert config.bm25_fallback_threshold == 0.5


def test_index_type_default():
    """验证 index_type 默认为 flat。"""
    config = MemoryBankConfig()
    assert config.index_type == "flat"


def test_ivf_nlist_default():
    """验证 ivf_nlist 默认值为 128。"""
    config = MemoryBankConfig()
    assert config.ivf_nlist == 128


def test_retrieval_alpha_zero_guarded():
    """传入 0.0 时守卫回退到默认值 0.7。"""
    config = MemoryBankConfig(retrieval_alpha=0.0)
    assert config.retrieval_alpha == 0.7


def test_retrieval_alpha_boundary_valid():
    """传入有效边界值 1.0 应通过。"""
    config = MemoryBankConfig(retrieval_alpha=1.0)
    assert config.retrieval_alpha == 1.0


def test_bm25_threshold_out_of_range_guarded():
    """传入 1.5 时守卫回退到默认值 0.5。"""
    config = MemoryBankConfig(bm25_fallback_threshold=1.5)
    assert config.bm25_fallback_threshold == 0.5


def test_ivf_nlist_zero_guarded():
    """传入 0 时守卫回退到默认值 128。"""
    config = MemoryBankConfig(ivf_nlist=0)
    assert config.ivf_nlist == 128


def test_bm25_threshold_zero_guarded():
    """验证 bm25_fallback_threshold=0.0 被守卫回退为 0.5。"""
    config = MemoryBankConfig(bm25_fallback_threshold=0.0)
    assert config.bm25_fallback_threshold == 0.5


def test_bm25_threshold_boundary_valid():
    """验证 bm25_fallback_threshold=1.0 边界有效值通过。"""
    config = MemoryBankConfig(bm25_fallback_threshold=1.0)
    assert config.bm25_fallback_threshold == 1.0


def test_ivf_nlist_negative_guarded():
    """验证 ivf_nlist=-1 被守卫回退为 128。"""
    config = MemoryBankConfig(ivf_nlist=-1)
    assert config.ivf_nlist == 128
