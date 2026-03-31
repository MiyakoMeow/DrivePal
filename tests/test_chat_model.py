"""Tests for ChatModel."""

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage

from app.models.chat import ChatModel
from app.models.settings import LLMProviderConfig


def _make_provider() -> LLMProviderConfig:
    """Create a mock LLM provider for testing."""
    return LLMProviderConfig(
        provider=MagicMock(
            model="test-model",
            api_key="test-key",
            base_url="http://localhost:8000/v1",
            temperature=0.0,
        )
    )


def test_generate_with_tools_single_round() -> None:
    """Test generate_with_tools handles single round tool calling."""
    provider = _make_provider()
    model = ChatModel(providers=[provider])

    fake_tool_call = {
        "name": "memory_update",
        "args": {"new_memory": "updated"},
        "id": "call_1",
        "type": "tool_call",
    }
    first_response = AIMessage(content="", tool_calls=[fake_tool_call])
    final_response = AIMessage(content="done")

    mock_client = MagicMock()
    bound = MagicMock()
    mock_client.bind_tools.return_value = bound
    bound.invoke.side_effect = [first_response, final_response]

    with patch.object(model, "_create_client", return_value=mock_client):
        result = model.generate_with_tools(
            prompt="test",
            tools=[
                {
                    "type": "function",
                    "function": {"name": "memory_update", "parameters": {}},
                }
            ],
            tool_executor=lambda name, args: "ok",
        )
    assert result == "done"


def test_generate_with_tools_no_tool_call() -> None:
    """Test generate_with_tools when no tool call is made."""
    provider = _make_provider()
    model = ChatModel(providers=[provider])

    mock_client = MagicMock()
    bound = MagicMock()
    mock_client.bind_tools.return_value = bound
    bound.invoke.return_value = AIMessage(content="direct answer")

    with patch.object(model, "_create_client", return_value=mock_client):
        result = model.generate_with_tools(
            prompt="test",
            tools=[],
            tool_executor=lambda name, args: "ok",
        )
    assert result == "direct answer"
