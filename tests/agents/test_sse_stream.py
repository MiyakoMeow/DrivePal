"""SSE 流式端点测试。mock LLM 以避免真实调用。"""

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.workflow import AgentWorkflow
from app.memory.types import MemoryMode


@pytest.fixture
def workflow():
    """mock MemoryModule + ChatModel 的 AgentWorkflow 实例。"""
    with (
        patch("app.agents.workflow.MemoryModule") as mock_mm,
        patch("app.agents.workflow.get_chat_model") as mock_get,
    ):
        mock_chat = AsyncMock()
        mock_chat.generate.return_value = '{"key": "value"}'
        mock_get.return_value = mock_chat
        mock_mm_instance = AsyncMock()
        mock_mm_instance.search.return_value = []
        mock_mm_instance.get_history.return_value = []
        mock_mm_instance.chat_model = mock_chat
        mock_mm.return_value = mock_mm_instance
        wf = AgentWorkflow(memory_mode=MemoryMode.MEMORY_BANK)
        yield wf


@pytest.mark.asyncio
async def test_run_stream_yields_context_done_first(workflow):
    """run_stream 首个事件应为 context_done（shortcut 除外）。"""
    events = []
    async for evt in workflow.run_stream("明天开会", session_id=None):
        events.append(evt)
    assert len(events) > 0
    assert events[0]["event"] == "stage_start"
    assert events[0]["data"]["stage"] == "context"


@pytest.mark.asyncio
async def test_run_stream_ends_with_done(workflow):
    """run_stream 最后事件应为 done。"""
    events = []
    async for evt in workflow.run_stream("明天开会"):
        events.append(evt)
    assert events[-1]["event"] == "done"


@pytest.mark.asyncio
async def test_run_stream_yields_all_stages(workflow):
    """run_stream 应产出 context/joint_decision/execution 三阶段事件。"""
    stages = set()
    async for evt in workflow.run_stream("明天开会"):
        if evt["event"] == "stage_start":
            stages.add(evt["data"]["stage"])
    assert stages == {"context", "joint_decision", "execution"}


@pytest.mark.asyncio
async def test_run_stream_shortcut_still_works(workflow):
    """快捷指令路径（如取消提醒）不应走完整流水线。"""
    events = []
    async for evt in workflow.run_stream("取消提醒"):
        events.append(evt)
    assert len(events) > 0
    assert events[0]["event"] in ("done", "error")
    stage_starts = [e for e in events if e["event"] == "stage_start"]
    assert len(stage_starts) == 0


@pytest.mark.asyncio
async def test_run_stream_error_yields_error_event(workflow):
    """LLM 调用失败时发出 error 事件。"""
    workflow._call_llm_json = AsyncMock(side_effect=RuntimeError("LLM down"))
    events = []
    async for evt in workflow.run_stream("明天开会"):
        events.append(evt)
    assert events[-1]["event"] == "error"


@pytest.mark.asyncio
async def test_run_with_stages_unchanged(workflow):
    """run_with_stages 仍返回 (str, str|None, WorkflowStages)。"""
    from app.agents.state import WorkflowStages

    result, event_id, stages = await workflow.run_with_stages("明天开会")
    assert isinstance(result, str)
    assert isinstance(stages, WorkflowStages)
