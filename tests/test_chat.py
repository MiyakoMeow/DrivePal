from unittest.mock import Mock, patch
from app.models.chat import ChatModel


def test_chat_model_init():
    model = ChatModel()
    assert model.model_name == "deepseek-chat"


@patch("app.models.chat.ChatOpenAI")
def test_generate(mock_openai):
    mock_instance = Mock()
    mock_instance.invoke.return_value = Mock(content="测试回复")
    mock_openai.return_value = mock_instance

    model = ChatModel()
    result = model.generate("你好")
    assert result == "测试回复"
