"""Scheduler 测试共享 fixtures."""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_workflow():
    wf = MagicMock()
    wf.current_user = "default"
    wf.memory_module = MagicMock()
    wf.memory_module.write = AsyncMock()
    wf.proactive_run = AsyncMock(return_value=("result", "evt1", MagicMock()))
    wf.execute_pending_reminder = AsyncMock(
        return_value=("result", "evt1", MagicMock())
    )
    return wf


@pytest.fixture
def mock_memory():
    mem = MagicMock()
    mem.search = AsyncMock(return_value=[])
    return mem
