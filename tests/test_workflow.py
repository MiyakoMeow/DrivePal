from unittest.mock import Mock, patch


@patch("app.agents.workflow.ChatModel")
def test_workflow_init(mock_chat):
    mock_instance = Mock()
    mock_instance.generate.return_value = '{"context": {}}'
    mock_chat.return_value = mock_instance

    from app.agents.workflow import AgentWorkflow

    workflow = AgentWorkflow()
    assert workflow.chat_model is not None


def test_workflow_init_with_memory_module():
    from app.agents.workflow import AgentWorkflow
    from app.memory.memory import MemoryModule

    memory = MemoryModule(data_dir="data/test")
    workflow = AgentWorkflow(memory_module=memory)

    assert workflow.memory_module is not None


@patch("app.agents.workflow.ChatModel")
def test_context_node_injects_memory_results(mock_chat):
    from unittest.mock import Mock
    from app.agents.workflow import AgentWorkflow
    from app.memory.memory import MemoryModule
    from langchain_core.messages import HumanMessage

    mock_instance = Mock()
    mock_instance.generate.return_value = (
        '{"context": {}, "related_events": [], "relevant_memories": []}'
    )
    mock_chat.return_value = mock_instance

    mock_memory = Mock(spec=MemoryModule)
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
