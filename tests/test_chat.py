"""聊天模型集成测试."""

from pathlib import Path

import pytest
from app.memory.memory import MemoryModule
from app.memory.schemas import MemoryEvent
from app.memory.types import MemoryMode
from app.models.chat import ChatModel
from app.models.settings import LLMProviderConfig
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agents.state import AgentState


@pytest.mark.integration
async def test_chat_drives_llm_memory_search(
    tmp_path: Path, llm_provider: LLMProviderConfig | None
) -> None:
    """验证聊天驱动的 LLM 记忆搜索能检索到相关事件."""
    if llm_provider is None:
        pytest.skip("No LLM provider available")
    chat_model = ChatModel(providers=[llm_provider])
    memory = MemoryModule(tmp_path, chat_model=chat_model)
    await memory.write(MemoryEvent(content="明天下午三点项目会议", type="meeting"))
    results = await memory.search("有什么会议安排", mode=MemoryMode.MEMORY_BANK)
    assert len(results) > 0
    assert "会议" in results[0].event["content"]


@pytest.mark.integration
async def test_chat_feeds_workflow_context(
    tmp_path: Path, llm_provider: LLMProviderConfig | None
) -> None:
    """验证记忆上下文被注入到代理工作流状态中."""
    if llm_provider is None:
        pytest.skip("No LLM provider available")
    from app.agents.workflow import AgentWorkflow

    memory = MemoryModule(tmp_path, chat_model=ChatModel(providers=[llm_provider]))
    await memory.write(MemoryEvent(content="下午三点开会", type="meeting"))
    workflow = AgentWorkflow(memory_module=memory)

    state: AgentState = {
        "messages": [{"role": "user", "content": "查一下会议"}],
        "context": {},
        "task": None,
        "decision": None,
        "result": None,
        "event_id": None,
    }
    result = await workflow._context_node(state)
    assert "related_events" in result["context"]
