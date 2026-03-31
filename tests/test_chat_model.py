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


def test_generate_with_tools_max_rounds_exceeded() -> None:
    """Test generate_with_tools raises when max_rounds is exceeded."""
    provider = _make_provider()
    model = ChatModel(providers=[provider])

    fake_tool_call = {
        "name": "memory_update",
        "args": {"new_memory": "updated"},
        "id": "call_1",
        "type": "tool_call",
    }
    tool_response = AIMessage(content="", tool_calls=[fake_tool_call])

    mock_client = MagicMock()
    bound = MagicMock()
    mock_client.bind_tools.return_value = bound
    bound.invoke.return_value = tool_response

    with patch.object(model, "_create_client", return_value=mock_client):
        try:
            model.generate_with_tools(
                prompt="test",
                tools=[
                    {
                        "type": "function",
                        "function": {"name": "memory_update", "parameters": {}},
                    }
                ],
                tool_executor=lambda name, args: "ok",
                max_rounds=1,
            )
            assert False, "Should have raised RuntimeError"
        except RuntimeError as e:
            assert "Max rounds" in str(e)


def test_generate_with_tools_max_rounds_one_round_completes() -> None:
    """Test generate_with_tools completes when single round finishes without tools."""
    provider = _make_provider()
    model = ChatModel(providers=[provider])

    fake_tool_call = {
        "name": "memory_update",
        "args": {"new_memory": "updated"},
        "id": "call_1",
        "type": "tool_call",
    }
    tool_response = AIMessage(content="", tool_calls=[fake_tool_call])
    final_response = AIMessage(content="final result")

    mock_client = MagicMock()
    bound = MagicMock()
    mock_client.bind_tools.return_value = bound
    bound.invoke.side_effect = [tool_response, final_response]

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
            max_rounds=2,
        )
    assert result == "final result"


def test_generate_with_tools_provider_fallback() -> None:
    """Test generate_with_tools falls back to next provider on failure."""
    provider1 = _make_provider()
    provider2 = _make_provider()
    model = ChatModel(providers=[provider1, provider2])

    mock_client2 = MagicMock()
    bound2 = MagicMock()
    mock_client2.bind_tools.return_value = bound2

    def create_client_side_effect(provider: object) -> MagicMock:
        if provider is provider1:
            raise RuntimeError("Provider 1 failed")
        return mock_client2

    bound2.invoke.return_value = AIMessage(content="fallback success")

    with patch.object(model, "_create_client", side_effect=create_client_side_effect):
        result = model.generate_with_tools(
            prompt="test",
            tools=[],
            tool_executor=lambda name, args: "ok",
        )
    assert result == "fallback success"


def test_generate_with_tools_null_tool_call_id_raises() -> None:
    """Test generate_with_tools raises when tool call has null id."""
    provider = _make_provider()
    model = ChatModel(providers=[provider])

    fake_tool_call = {
        "name": "memory_update",
        "args": {"new_memory": "updated"},
        "id": None,
        "type": "tool_call",
    }
    tool_response = AIMessage(content="", tool_calls=[fake_tool_call])

    mock_client = MagicMock()
    bound = MagicMock()
    mock_client.bind_tools.return_value = bound
    bound.invoke.return_value = tool_response

    with patch.object(model, "_create_client", return_value=mock_client):
        try:
            model.generate_with_tools(
                prompt="test",
                tools=[
                    {
                        "type": "function",
                        "function": {"name": "memory_update", "parameters": {}},
                    }
                ],
                tool_executor=lambda name, args: "ok",
            )
            assert False, "Should have raised RuntimeError"
        except RuntimeError as e:
            assert "null id" in str(e)


def test_generate_with_tools_tool_call_with_missing_name_in_args() -> None:
    """Test generate_with_tools handles tool call where name is missing from args."""
    provider = _make_provider()
    model = ChatModel(providers=[provider])

    fake_tool_call = {
        "name": "memory_update",
        "args": {},
        "id": "call_1",
        "type": "tool_call",
    }
    tool_response = AIMessage(content="", tool_calls=[fake_tool_call])
    final_response = AIMessage(content="done")

    mock_client = MagicMock()
    bound = MagicMock()
    mock_client.bind_tools.return_value = bound
    bound.invoke.side_effect = [tool_response, final_response]

    results: list[str] = []

    def fake_executor(name: str, args: dict) -> str:
        results.append(name)
        return "ok"

    with patch.object(model, "_create_client", return_value=mock_client):
        result = model.generate_with_tools(
            prompt="test",
            tools=[
                {
                    "type": "function",
                    "function": {"name": "memory_update", "parameters": {}},
                }
            ],
            tool_executor=fake_executor,
        )
    assert result == "done"
    assert results == ["memory_update"]
