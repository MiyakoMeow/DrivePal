"""MemoryLifecycle inflight 防护测试。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.memory.memory_bank.config import MemoryBankConfig
from app.memory.memory_bank.lifecycle import MemoryLifecycle


@pytest.mark.asyncio
async def test_inflight_prevents_duplicate_summarize():
    """Given inflight 摘要在运行，When 同日期再次触发，Then 不创建新任务。"""
    config = MemoryBankConfig(enable_summary=True)
    index = MagicMock()
    embed = AsyncMock()
    forget = MagicMock()
    summarizer = AsyncMock()
    bg = MagicMock()

    lifecycle = MemoryLifecycle(index, embed, forget, summarizer, config, bg)
    date_key = "2024-06-15"

    await lifecycle._trigger_background_summarize(date_key)
    assert bg.spawn.call_count == 1

    await lifecycle._trigger_background_summarize(date_key)
    assert bg.spawn.call_count == 1

    other_date = "2024-06-16"
    await lifecycle._trigger_background_summarize(other_date)
    assert bg.spawn.call_count == 2
