"""Summarizer 单元测试（mock LLM）。"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.memory.exceptions import LLMCallFailed, SummarizationEmpty
from app.memory.memory_bank.config import MemoryBankConfig
from app.memory.memory_bank.index import FaissIndex
from app.memory.memory_bank.summarizer import GENERATION_EMPTY, Summarizer

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
        summ = Summarizer(mock_llm, idx, MemoryBankConfig())
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
        summ = Summarizer(mock_llm, idx, MemoryBankConfig())
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
        mock_llm.call = AsyncMock(side_effect=SummarizationEmpty())
        summ = Summarizer(mock_llm, idx, MemoryBankConfig())
        result = await summ.get_daily_summary("2024-06-15")
        assert result is None


@pytest.mark.asyncio
async def test_summarize_prompt_includes_user_focus():
    """验证摘要 prompt 包含按姓名追踪偏好引导。"""
    with tempfile.TemporaryDirectory() as tmp:
        idx = FaissIndex(Path(tmp))
        await idx.load()
        await idx.add_vector(
            "Gary: seat 45",
            TEST_EMBEDDING,
            "2024-06-15T00:00:00",
            {"source": "2024-06-15"},
        )
        mock_llm = AsyncMock()
        mock_llm.call = AsyncMock(return_value="summary text")
        summ = Summarizer(mock_llm, idx, MemoryBankConfig())
        await summ.get_daily_summary("2024-06-15")
        call_args = mock_llm.call.call_args
        call_text = (
            call_args.args[0] if call_args.args else call_args.kwargs.get("prompt", "")
        )
        assert (
            "Which person (by name) expressed or changed each preference" in call_text
        )


@pytest.mark.asyncio
async def test_overall_summary_skips_when_exists():
    """extra 已有 overall_summary → 返回 None（不调 LLM）。"""
    with tempfile.TemporaryDirectory() as tmp:
        idx = FaissIndex(Path(tmp))
        await idx.load()
        idx.set_extra({"overall_summary": "already generated"})
        await idx.add_vector(
            "daily summary content",
            TEST_EMBEDDING,
            "2024-06-15T00:00:00",
            {"type": "daily_summary", "source": "summary_2024-06-15"},
        )
        mock_llm = AsyncMock()
        summ = Summarizer(mock_llm, idx, MemoryBankConfig())
        result = await summ.get_overall_summary()
        assert result is None
        mock_llm.call.assert_not_called()


@pytest.mark.asyncio
async def test_overall_personality_skips_when_exists():
    """extra 已有 overall_personality → 返回 None。"""
    with tempfile.TemporaryDirectory() as tmp:
        idx = FaissIndex(Path(tmp))
        await idx.load()
        idx.set_extra(
            {
                "overall_personality": "existing",
                "daily_personalities": {"2024-06-15": "some traits"},
            }
        )
        mock_llm = AsyncMock()
        summ = Summarizer(mock_llm, idx, MemoryBankConfig())
        result = await summ.get_overall_personality()
        assert result is None
        mock_llm.call.assert_not_called()


@pytest.mark.asyncio
async def test_llm_call_failed_propagates():
    """LLMCallFailed 应上抛（不被 Summarizer 吞）。"""
    with tempfile.TemporaryDirectory() as tmp:
        idx = FaissIndex(Path(tmp))
        await idx.load()
        await idx.add_vector(
            "test",
            TEST_EMBEDDING,
            "2024-06-15T00:00:00",
            {"source": "2024-06-15"},
        )
        mock_llm = AsyncMock()
        mock_llm.call = AsyncMock(side_effect=LLMCallFailed("API error"))
        summ = Summarizer(mock_llm, idx, MemoryBankConfig())
        with pytest.raises(LLMCallFailed):
            await summ.get_daily_summary("2024-06-15")


@pytest.mark.asyncio
async def test_overall_summary_empty_sets_sentinel():
    """LLM 空返回 → overall_summary 置为 GENERATION_EMPTY，方法返回 None。"""
    with tempfile.TemporaryDirectory() as tmp:
        idx = FaissIndex(Path(tmp))
        await idx.load()
        await idx.add_vector(
            "daily summary content",
            TEST_EMBEDDING,
            "2024-06-15T00:00:00",
            {"type": "daily_summary", "source": "summary_2024-06-15"},
        )
        mock_llm = AsyncMock()
        mock_llm.call = AsyncMock(side_effect=SummarizationEmpty())
        summ = Summarizer(mock_llm, idx, MemoryBankConfig())
        result = await summ.get_overall_summary()
        assert result is None
        assert idx.get_extra().get("overall_summary") == GENERATION_EMPTY


@pytest.mark.asyncio
async def test_daily_personality_skips_when_exists():
    """extra daily_personalities 已有日期键 → 返回 None。"""
    with tempfile.TemporaryDirectory() as tmp:
        idx = FaissIndex(Path(tmp))
        await idx.load()
        idx.set_extra({"daily_personalities": {"2024-06-15": "existing traits"}})
        await idx.add_vector(
            "test",
            TEST_EMBEDDING,
            "2024-06-15T00:00:00",
            {"source": "2024-06-15"},
        )
        mock_llm = AsyncMock()
        summ = Summarizer(mock_llm, idx, MemoryBankConfig())
        result = await summ.get_daily_personality("2024-06-15")
        assert result is None
        mock_llm.call.assert_not_called()
