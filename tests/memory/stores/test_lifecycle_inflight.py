"""MemoryLifecycle finalize 测试."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.memory.memory_bank.config import MemoryBankConfig
from app.memory.memory_bank.lifecycle import MemoryLifecycle


def _make_index() -> MagicMock:
    index = MagicMock()
    index.save = AsyncMock()
    index.add_vector = AsyncMock()
    index.remove_vectors = AsyncMock()
    return index


@pytest.mark.asyncio
async def test_finalize_generates_summaries():
    """finalize 遍历 source，串行生成摘要/人格."""
    index = _make_index()
    index.get_metadata.return_value = [
        {"source": "2024-06-15"},
        {"source": "2024-06-16"},
    ]
    index.get_extra.return_value = {}
    embed = AsyncMock()
    embed.encode = AsyncMock(return_value=[0.1] * 1536)
    forget = MagicMock()
    forget.rng = None
    summarizer = AsyncMock()
    summarizer.get_daily_summary = AsyncMock(return_value="daily summary")
    summarizer.get_daily_personality = AsyncMock(return_value="personality")
    summarizer.get_overall_summary = AsyncMock(return_value="overall")
    summarizer.get_overall_personality = AsyncMock(return_value="overall personality")
    config = MemoryBankConfig()

    lifecycle = MemoryLifecycle(index, embed, forget, summarizer, config)
    await lifecycle.finalize()

    assert summarizer.get_daily_summary.call_count == 2
    assert summarizer.get_daily_personality.call_count == 2
    assert summarizer.get_overall_summary.call_count == 1
    assert summarizer.get_overall_personality.call_count == 1
    # get_daily_summary 有返回值 → add_vector 被调用
    assert index.add_vector.call_count == 2  # 两天的摘要向量


@pytest.mark.asyncio
async def test_finalize_skips_existing_summaries():
    """已有摘要的日期跳过生成."""
    index = _make_index()
    index.get_metadata.return_value = [
        {"source": "2024-06-15"},
        {"source": "2024-06-16"},
    ]
    index.get_extra.return_value = {}
    embed = AsyncMock()
    embed.encode = AsyncMock(return_value=[0.1] * 1536)
    forget = MagicMock()
    forget.rng = None
    config = MemoryBankConfig()

    async def mock_daily_summary(date_key: str) -> str | None:
        if date_key == "2024-06-15":
            return None  # 已存在
        return "new summary"

    summarizer = AsyncMock()
    summarizer.get_daily_summary = mock_daily_summary
    summarizer.get_daily_personality = AsyncMock(return_value="personality")
    summarizer.get_overall_summary = AsyncMock(return_value="overall")
    summarizer.get_overall_personality = AsyncMock(return_value="overall personality")

    lifecycle = MemoryLifecycle(index, embed, forget, summarizer, config)
    await lifecycle.finalize()

    # 只有 2024-06-16 的摘要新增向量
    assert index.add_vector.call_count == 1


@pytest.mark.asyncio
async def test_finalize_without_summarizer_just_saves():
    """无 summarizer 时仅保存."""
    index = _make_index()
    embed = AsyncMock()
    forget = MagicMock()

    lifecycle = MemoryLifecycle(index, embed, forget, None, MemoryBankConfig())
    await lifecycle.finalize()

    assert index.save.called


@pytest.mark.asyncio
async def test_finalize_with_forgetting():
    """enable_forgetting=True 时 finalize 执行遗忘."""
    index = _make_index()
    index.get_metadata.return_value = [
        {
            "faiss_id": 0,
            "memory_strength": 1,
            "timestamp": "2024-01-01T00:00:00",
            "last_recall_date": "2024-01-01",
        },
    ]
    embed = AsyncMock()
    forget = MagicMock()
    forget.rng = None
    # purge_forgotten 会调 maybe_forget 并可能调 remove_vectors
    forget.maybe_forget.return_value = None  # 节流跳过

    config = MemoryBankConfig(enable_forgetting=True)
    lifecycle = MemoryLifecycle(index, embed, forget, None, config)
    await lifecycle.finalize()

    # purge_forgotten 被调用（maybe_forget 因节流返回 None，不调 remove_vectors）
    assert forget.maybe_forget.called
    assert index.save.called
