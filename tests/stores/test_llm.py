"""LlmClient 重试策略测试。"""

import pytest

from app.memory.stores.memory_bank.llm import LlmClient
from app.models.chat import AllProviderFailedError


class _MockChatModel:
    """模拟 ChatModel，控制失败次数和错误类型。"""

    def __init__(self, error_message: str = "connection error"):
        self._call_count = 0
        self._error_message = error_message

    async def generate(self, prompt: str, **kwargs):
        self._call_count += 1
        raise AllProviderFailedError(self._error_message)


class _AlternatingModel:
    """先失败 N 次然后成功。"""

    def __init__(self, fail_count: int = 1, error_message: str = "rate limit"):
        self._call_count = 0
        self._fail_count = fail_count
        self._error_message = error_message

    async def generate(self, prompt: str, **kwargs):
        self._call_count += 1
        if self._call_count <= self._fail_count:
            raise AllProviderFailedError(self._error_message)
        return "final response"


class _ContextTrimModel:
    """首次失败标记为上下文超长，第二次成功。"""

    def __init__(self):
        self._call_count = 0

    async def generate(self, prompt: str, **kwargs):
        self._call_count += 1
        if self._call_count == 1:
            raise AllProviderFailedError("maximum context length exceeded")
        return "trimmed response"


@pytest.mark.asyncio
async def test_llm_retry_on_transient():
    """瞬态错误（rate limit）会重试直到耗尽。"""
    model = _MockChatModel("rate limit exceeded")
    client = LlmClient(model)
    result = await client.call("test")
    assert result is None
    assert model._call_count == 3  # 默认重试 3 次


@pytest.mark.asyncio
async def test_llm_transient_then_success():
    """瞬态错误后重试成功。"""
    model = _AlternatingModel(fail_count=2)
    client = LlmClient(model)
    result = await client.call("test")
    assert result == "final response"
    assert model._call_count == 3


@pytest.mark.asyncio
async def test_llm_context_trim_on_long_prompt():
    """上下文超长时截断 prompt 后重试。"""
    model = _ContextTrimModel()
    client = LlmClient(model)
    long_prompt = "X" * 2000
    result = await client.call(long_prompt)
    assert result == "trimmed response"
    assert model._call_count == 2


@pytest.mark.asyncio
async def test_llm_nontransient_exhausts_retries():
    """非瞬态错误（鉴权失败）也会重试（当前策略：无条件重试）。"""
    model = _MockChatModel("Incorrect API key")
    client = LlmClient(model)
    result = await client.call("test")
    assert result is None
    # 当前策略对所有 AllProviderFailedError 都重试，不管错误类型
    assert model._call_count == 3
