import pytest

from app.memory.memory import MemoryModule
from app.models.chat import ChatModel
from tests.conftest import is_vllm_unavailable

SKIP_IF_NO_VLLM = pytest.mark.skipif(
    is_vllm_unavailable(),
    reason="vLLM not available at http://localhost:8000",
)


@SKIP_IF_NO_VLLM
def test_chat_drives_llm_memory_search(tmp_path):
    chat_model = ChatModel()
    memory = MemoryModule(str(tmp_path), chat_model=chat_model)
    memory.write({"content": "明天下午三点项目会议", "type": "meeting"})
    results = memory.search("有什么会议安排", mode="llm_only")
    assert len(results) > 0
    assert "会议" in results[0]["content"]


@SKIP_IF_NO_VLLM
def test_chat_feeds_workflow_context(tmp_path):
    from app.agents.workflow import AgentWorkflow
    from langchain_core.messages import HumanMessage

    memory = MemoryModule(str(tmp_path), chat_model=ChatModel())
    memory.write({"content": "下午三点开会", "type": "meeting"})
    workflow = AgentWorkflow(memory_module=memory)
    state = {
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
