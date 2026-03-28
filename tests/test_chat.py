"""Tests for the chat model integration."""

import pytest

from app.memory.memory import MemoryModule
from app.memory.types import MemoryMode
from app.models.chat import ChatModel
from tests.conftest import is_llm_available

SKIP_IF_NO_LLM = pytest.mark.skipif(
    not is_llm_available(),
    reason="OPENAI_MODEL not set",
)


@SKIP_IF_NO_LLM
def test_chat_drives_llm_memory_search(tmp_path):
    """Verify that chat-driven LLM memory search retrieves relevant events."""
    chat_model = ChatModel()
    memory = MemoryModule(str(tmp_path), chat_model=chat_model)
    memory.write({"content": "明天下午三点项目会议", "type": "meeting"})
    results = memory.search("有什么会议安排", mode=MemoryMode.LLM_ONLY)
    assert len(results) > 0
    assert "会议" in results[0]["content"]


@SKIP_IF_NO_LLM
def test_chat_feeds_workflow_context(tmp_path):
    """Verify that memory context is injected into the agent workflow state."""
    from app.agents.workflow import AgentWorkflow
    from langchain_core.messages import HumanMessage

    memory = MemoryModule(str(tmp_path), chat_model=ChatModel())
    memory.write({"content": "下午三点开会", "type": "meeting"})
    workflow = AgentWorkflow(memory_module=memory)
    from app.agents.state import AgentState

    state: AgentState = {
        "messages": [HumanMessage(content="查一下会议")],
        "context": {},
        "task": None,
        "decision": None,
        "memory_mode": "keyword",
        "result": None,
        "event_id": None,
    }
    result = workflow._context_node(state)
    assert "related_events" in result["context"]
