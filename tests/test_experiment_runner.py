from app.experiment.test_data import TestDataGenerator


def test_seed_reproducibility():
    gen = TestDataGenerator(config_dir="config")
    cases_a = gen.generate_test_cases(count=5, seed=42)
    cases_b = gen.generate_test_cases(count=5, seed=42)
    assert [c["input"] for c in cases_a] == [c["input"] for c in cases_b]


def test_seed_produces_different_without_seed():
    gen = TestDataGenerator(config_dir="config")
    cases_a = gen.generate_test_cases(count=5, seed=42)
    cases_b = gen.generate_test_cases(count=5, seed=99)
    inputs_a = [c["input"] for c in cases_a]
    inputs_b = [c["input"] for c in cases_b]
    assert inputs_a != inputs_b or len(set(inputs_a)) == 1


def test_raw_preserved_in_context_node():
    from unittest.mock import MagicMock
    from app.agents.workflow import AgentWorkflow

    mock_chat = MagicMock()
    mock_chat.generate.return_value = '{"time": "10:00", "location": "home"}'
    workflow = AgentWorkflow.__new__(AgentWorkflow)
    workflow.data_dir = "data"
    workflow.memory_mode = "keyword"
    workflow.memory = MagicMock()
    workflow.memory.search.return_value = []
    workflow.memory.get_history.return_value = []
    workflow.memory.chat_model = mock_chat

    from app.agents.state import AgentState
    from langchain_core.messages import HumanMessage

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
    from unittest.mock import MagicMock, patch
    from app.agents.workflow import AgentWorkflow

    mock_chat = MagicMock()
    mock_chat.generate.return_value = '{"should_remind": false, "reasoning": "test"}'
    workflow = AgentWorkflow.__new__(AgentWorkflow)
    workflow.data_dir = "data"
    workflow.memory_mode = "keyword"
    workflow.memory = MagicMock()
    workflow.memory.chat_model = mock_chat

    from app.agents.state import AgentState
    from langchain_core.messages import HumanMessage

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
