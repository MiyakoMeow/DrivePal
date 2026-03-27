from unittest.mock import Mock, patch


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


def test_context_node_injects_memory_results():
    from unittest.mock import Mock
    from app.agents.workflow import AgentWorkflow
    from app.memory.memory import MemoryModule
    from langchain_core.messages import HumanMessage

    mock_memory = Mock()
    mock_memory.chat_model.generate.return_value = '{"context": {}}'
    mock_memory.search.return_value = [
        {"id": "1", "content": "明天9点开会", "created_at": "2026-03-26"}
    ]
    mock_memory.get_history.return_value = []

    workflow = AgentWorkflow(memory_module=mock_memory)

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

    mock_memory.search.assert_called_once()

    assert "related_events" in result_state["context"]
    assert "relevant_memories" in result_state["context"]
    assert (
        result_state["context"]["related_events"]
        == result_state["context"]["relevant_memories"]
    )
