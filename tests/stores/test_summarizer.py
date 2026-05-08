"""Summarizer 单元测试（多用户版，mock LLM）。"""

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from app.memory.memory_bank.faiss_index import FaissIndexManager
from app.memory.memory_bank.summarizer import Summarizer

TEST_EMBEDDING = [0.1] * 1536


@pytest.fixture
def manager(tmp_path: Path) -> FaissIndexManager:
    return FaissIndexManager(tmp_path)


@pytest.mark.asyncio
async def test_get_daily_summary_returns_text(manager: FaissIndexManager):
    """验证 get_daily_summary 返回摘要文本。"""
    uid = "user_1"
    await manager.add_vector(
        uid,
        "Gary likes seat at 30",
        TEST_EMBEDDING,
        "2024-06-15T00:00:00",
        {"source": "2024-06-15"},
    )

    mock_llm = AsyncMock()
    mock_llm.call = AsyncMock(return_value="User Gary prefers seat at 30%")
    summ = Summarizer(mock_llm, manager)
    result = await summ.get_daily_summary(uid, "2024-06-15")
    assert result is not None
    assert "Gary" in result


@pytest.mark.asyncio
async def test_get_daily_summary_returns_none_when_exists(manager: FaissIndexManager):
    """验证已有摘要时返回 None。"""
    uid = "user_1"
    await manager.add_vector(
        uid,
        "test",
        TEST_EMBEDDING,
        "2024-06-15T00:00:00",
        {"source": "summary_2024-06-15", "type": "daily_summary"},
    )
    mock_llm = AsyncMock()
    summ = Summarizer(mock_llm, manager)
    result = await summ.get_daily_summary(uid, "2024-06-15")
    assert result is None


@pytest.mark.asyncio
async def test_get_daily_summary_none_on_empty_llm(manager: FaissIndexManager):
    """验证 LLM 返回空时结果为 None。"""
    uid = "user_1"
    await manager.add_vector(
        uid, "test", TEST_EMBEDDING, "2024-06-15T00:00:00", {"source": "2024-06-15"}
    )
    mock_llm = AsyncMock()
    mock_llm.call = AsyncMock(return_value=None)
    summ = Summarizer(mock_llm, manager)
    result = await summ.get_daily_summary(uid, "2024-06-15")
    assert result is None


@pytest.mark.asyncio
async def test_summarize_prompt_includes_user_focus(manager: FaissIndexManager):
    """验证摘要 prompt 包含按姓名追踪偏好引导。"""
    uid = "user_1"
    await manager.add_vector(
        uid,
        "Gary: seat 45",
        TEST_EMBEDDING,
        "2024-06-15T00:00:00",
        {"source": "2024-06-15"},
    )
    mock_llm = AsyncMock()
    mock_llm.call = AsyncMock(return_value="summary text")
    summ = Summarizer(mock_llm, manager)
    await summ.get_daily_summary(uid, "2024-06-15")
    call_args = mock_llm.call.call_args
    call_text = (
        call_args.args[0] if call_args.args else call_args.kwargs.get("prompt", "")
    )
    assert "Which person (by name) expressed or changed each preference" in call_text
