import pytest
import os

SKIP_IF_NO_API_KEY = pytest.mark.skipif(
    not os.getenv("DEEPSEEK_API_KEY"),
    reason="DEEPSEEK_API_KEY not set",
)


@SKIP_IF_NO_API_KEY
def test_workflow_init():
    from app.agents.workflow import AgentWorkflow

    workflow = AgentWorkflow()
    assert workflow.memory.chat_model is not None


def test_workflow_init_with_memory_module():
    from app.agents.workflow import AgentWorkflow
    from app.memory.memory import MemoryModule

    memory = MemoryModule(data_dir="data/test")
    workflow = AgentWorkflow(memory_module=memory)

    assert workflow.memory_module is not None


@SKIP_IF_NO_API_KEY
def test_context_node_injects_memory_results():
    from app.agents.workflow import AgentWorkflow
    from app.memory.memory import MemoryModule
    from app.models.chat import ChatModel
    from langchain_core.messages import HumanMessage

    chat_model = ChatModel()
    memory = MemoryModule(data_dir="data/test", chat_model=chat_model)
    workflow = AgentWorkflow(memory_module=memory)

    state = {
        "messages": [HumanMessage(content="明天有什么安排")],
        "context": {},
        "task": None,
        "decision": None,
        "memory_mode": "keyword",
        "result": None,
        "event_id": None,
    }

    result_state = workflow._context_node(state)

    assert "related_events" in result_state["context"]
    assert "relevant_memories" in result_state["context"]
