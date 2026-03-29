"""Tests for workflow node raw output preservation."""

from unittest.mock import MagicMock, patch

from app.agents.state import AgentState
from app.agents.workflow import AgentWorkflow
from langchain_core.messages import HumanMessage


def test_raw_preserved_in_context_node():
    """Verify that raw LLM output is preserved in the context node."""
    mock_chat = MagicMock()
    mock_chat.generate.return_value = '{"time": "10:00", "location": "home"}'
    workflow = AgentWorkflow.__new__(AgentWorkflow)
    workflow.data_dir = "data"
    workflow.memory_mode = "keyword"
    workflow.memory_module = MagicMock()
    workflow.memory_module.search.return_value = []
    workflow.memory_module.get_history.return_value = []
    workflow.memory_module.chat_model = mock_chat

    state: AgentState = {
        "messages": [HumanMessage(content="现在几点")],
        "context": {},
        "task": {},
        "decision": {},
        "memory_mode": "keyword",
        "result": None,
        "event_id": None,
    }
    result = workflow._context_node(state)
    assert result["context"].get("raw") is not None


def test_raw_preserved_in_strategy_node():
    """Verify that raw LLM output is preserved in the strategy node."""
    mock_chat = MagicMock()
    mock_chat.generate.return_value = '{"should_remind": false, "reasoning": "test"}'
    workflow = AgentWorkflow.__new__(AgentWorkflow)
    workflow.data_dir = "data"
    workflow.memory_mode = "keyword"
    workflow.memory_module = MagicMock()
    workflow.memory_module.chat_model = mock_chat

    with patch("app.agents.workflow.JSONStore") as mock_store_cls:
        mock_store = MagicMock()
        mock_store.read.return_value = {"reminder_weights": {"default": 1.0}}
        mock_store_cls.return_value = mock_store

        state: AgentState = {
            "messages": [HumanMessage(content="test")],
            "context": {},
            "task": {},
            "decision": {},
            "memory_mode": "keyword",
            "result": None,
            "event_id": None,
        }
        result = workflow._strategy_node(state)
        assert result["decision"].get("raw") is not None
