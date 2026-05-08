"""LlmClient 重试策略测试。"""

import pytest

from app.memory.memory_bank.llm import LlmClient
from app.models.chat import AllProviderFailedError


class _ConstErrorModel:
    """固定失败的模拟 ChatModel。"""

    def __init__(self, error_message: str = "connection error"):
        self.call_count = 0
        self._error_message = error_message

    async def generate(self, **_kwargs):
        self.call_count += 1
        raise AllProviderFailedError(self._error_message)


class _AlternatingModel:
    """先失败 N 次然后成功。"""

    def __init__(self, fail_count: int = 1, error_message: str = "rate limit"):
        self.call_count = 0
        self._fail_count = fail_count
        self._error_message = error_message

    async def generate(self, **_kwargs):
        self.call_count += 1
        if self.call_count <= self._fail_count:
            raise AllProviderFailedError(self._error_message)
        return "final response"


class _ContextTrimModel:
    """首次失败标记为上下文超长，第二次成功。"""

    def __init__(self):
        self.call_count = 0

    async def generate(self, **_kwargs):
        self.call_count += 1
        if self.call_count == 1:
            msg = "maximum context length exceeded"
            raise AllProviderFailedError(msg)
        return "trimmed response"


async def _noop_sleep(*_: object) -> None:
    return None


@pytest.mark.asyncio
async def test_llm_retry_on_transient(monkeypatch: pytest.MonkeyPatch):
    """瞬态错误（rate limit）会重试直到耗尽。"""
    monkeypatch.setattr("app.memory.memory_bank.llm._sleep", _noop_sleep)
    model = _ConstErrorModel("rate limit exceeded")
    client = LlmClient(model)
    result = await client.call("test")
    assert result is None
    assert model.call_count == 3  # 瞬态错误重试 3 次


@pytest.mark.asyncio
async def test_llm_transient_then_success(monkeypatch: pytest.MonkeyPatch):
    """瞬态错误后重试成功。"""
    monkeypatch.setattr("app.memory.memory_bank.llm._sleep", _noop_sleep)
    model = _AlternatingModel(fail_count=2)
    client = LlmClient(model)
    result = await client.call("test")
    assert result == "final response"
    assert model.call_count == 3


@pytest.mark.asyncio
async def test_llm_context_trim_on_long_prompt():
    """上下文超长时截断 prompt 后重试。"""
    model = _ContextTrimModel()
    client = LlmClient(model)
    long_prompt = "X" * 2000
    result = await client.call(long_prompt)
    assert result == "trimmed response"
    assert model.call_count == 2


@pytest.mark.asyncio
async def test_llm_nontransient_exhausts_retries():
    """非瞬态错误（鉴权失败）快速失败，仅重试一次。"""
    model = _ConstErrorModel("Incorrect API key")
    client = LlmClient(model)
    result = await client.call("test")
    assert result is None
    assert model.call_count == 2


class _MessagesRecorder:
    """记录 generate() 收到的 messages 参数。"""

    def __init__(self, response: str = "test response"):
        self.response = response
        self.last_messages = None
        self.call_count = 0

    async def generate(
        self, *, prompt=None, system_prompt=None, messages=None, **_kwargs
    ):
        self.call_count += 1
        self.last_messages = messages
        return self.response


@pytest.mark.asyncio
async def test_llm_sends_four_message_sequence():
    """LlmClient.call() 应构建 4 消息序列（system→user→assistant→user）。"""
    recorder = _MessagesRecorder()
    client = LlmClient(recorder)
    await client.call("summarize this", system_prompt="You are a helper")
    assert recorder.last_messages is not None
    assert len(recorder.last_messages) == 4
    assert recorder.last_messages[0] == {
        "role": "system",
        "content": "You are a helper",
    }
    assert recorder.last_messages[1]["role"] == "user"
    assert recorder.last_messages[2]["role"] == "assistant"
    assert recorder.last_messages[3]["role"] == "user"
    assert recorder.last_messages[3]["content"] == "summarize this"


class _ContextTrimRecorder(_MessagesRecorder):
    """首次上下文超长失败，第二次成功；同时记录 messages。"""

    def __init__(self):
        super().__init__(response="trimmed response")
        self.trimmed_messages = None

    async def generate(self, **kwargs):
        self.call_count += 1
        self.last_messages = kwargs.get("messages")
        if self.call_count == 1:
            exc = AllProviderFailedError("maximum context length exceeded")
            raise exc
        self.trimmed_messages = kwargs.get("messages")
        return self.response


@pytest.mark.asyncio
async def test_llm_context_trim_shortens_last_message():
    """上下文超长时应截断 messages[-1]["content"]。"""
    model = _ContextTrimRecorder()
    client = LlmClient(model)
    long_prompt = "X" * 2000
    result = await client.call(long_prompt)
    assert result == "trimmed response"
    assert model.call_count == 2
    assert model.trimmed_messages is not None
    assert len(model.trimmed_messages[-1]["content"]) < len(long_prompt)
