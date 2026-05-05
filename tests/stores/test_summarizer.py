"""Summarizer 单元测试（mock LLM）。"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.memory.stores.memory_bank.faiss_index import FaissIndex
from app.memory.stores.memory_bank.summarizer import Summarizer

TEST_EMBEDDING = [0.1] * 1536


@pytest.mark.asyncio
async def test_get_daily_summary_returns_text():
    """验证 get_daily_summary 返回摘要文本。"""
    with tempfile.TemporaryDirectory() as tmp:
        idx = FaissIndex(Path(tmp))
        await idx.load()
        await idx.add_vector(
            "Gary likes seat at 30",
            TEST_EMBEDDING,
            "2024-06-15T00:00:00",
            {"source": "2024-06-15"},
        )

        mock_llm = AsyncMock()
        mock_llm.call = AsyncMock(return_value="User Gary prefers seat at 30%")
        summ = Summarizer(mock_llm, idx)
        result = await summ.get_daily_summary("2024-06-15")
        assert result is not None
        assert "Gary" in result


@pytest.mark.asyncio
async def test_get_daily_summary_returns_none_when_exists():
    """验证已有摘要时返回 None。"""
    with tempfile.TemporaryDirectory() as tmp:
        idx = FaissIndex(Path(tmp))
        await idx.load()
        await idx.add_vector(
            "test",
            TEST_EMBEDDING,
            "2024-06-15T00:00:00",
            {"source": "summary_2024-06-15", "type": "daily_summary"},
        )
        mock_llm = AsyncMock()
        summ = Summarizer(mock_llm, idx)
        result = await summ.get_daily_summary("2024-06-15")
        assert result is None


@pytest.mark.asyncio
async def test_get_daily_summary_none_on_empty_llm():
    """验证 LLM 返回空时结果为 None。"""
    with tempfile.TemporaryDirectory() as tmp:
        idx = FaissIndex(Path(tmp))
        await idx.load()
        await idx.add_vector(
            "test", TEST_EMBEDDING, "2024-06-15T00:00:00", {"source": "2024-06-15"}
        )
        mock_llm = AsyncMock()
        mock_llm.call = AsyncMock(return_value=None)
        summ = Summarizer(mock_llm, idx)
        result = await summ.get_daily_summary("2024-06-15")
        assert result is None
