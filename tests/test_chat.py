import pytest
import os
from app.models.chat import ChatModel

SKIP_IF_NO_API_KEY = pytest.mark.skipif(
    not os.getenv("DEEPSEEK_API_KEY"),
    reason="DEEPSEEK_API_KEY not set",
)


@SKIP_IF_NO_API_KEY
def test_chat_model_init():
    model = ChatModel()
    assert model.model_name == "deepseek-chat"


@SKIP_IF_NO_API_KEY
def test_generate():
    model = ChatModel()
    result = model.generate("你好")
    assert isinstance(result, str)
    assert len(result) > 0
