"""测试 AgentWorkflow proactive_run 模式."""

import os

import pytest

from app.agents.workflow import AgentWorkflow


@pytest.mark.skipif(
    not os.getenv("OPENROUTER_API_KEY"),
    reason="需要 LLM API key 才能运行",
)
@pytest.mark.asyncio
async def test_proactive_run_with_context_override():
    """proactive_run 传入 context_override 时应跳过 LLM context 节点直接走向决策和执行。"""
    wf = AgentWorkflow()
    result, event_id, stages = await wf.proactive_run(
        context_override={"scenario": "parked", "spatial": {}},
        trigger_source="test",
    )
    assert isinstance(result, str)
    assert len(result) > 0
