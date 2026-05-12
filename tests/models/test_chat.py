"""ChatModel 客户端缓存测试."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from app.models.chat import (
    ChatModel,
    _get_cached_client,
    clear_semaphore_cache,
    close_client_cache,
)
from app.models.settings import LLMProviderConfig
from app.models.types import ProviderConfig as PCfg

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture(autouse=True)
async def _clean_cache() -> AsyncIterator[None]:
    """每个测试前后清理客户端缓存."""
    clear_semaphore_cache()
    yield
    await close_client_cache()
    clear_semaphore_cache()


@pytest.mark.asyncio
async def test_cached_client_reuse():
    """同 base_url+api_key 返回同一 AsyncOpenAI 实例."""
    provider = LLMProviderConfig(
        provider=PCfg(model="m", base_url="http://x", api_key="k"), concurrency=4
    )
    c1 = await _get_cached_client(provider)
    c2 = await _get_cached_client(provider)
    assert c1 is c2


@pytest.mark.asyncio
async def test_cached_client_different_keys():
    """不同 api_key 返回不同实例."""
    p1 = LLMProviderConfig(
        provider=PCfg(model="m", base_url="http://x", api_key="k1"), concurrency=4
    )
    p2 = LLMProviderConfig(
        provider=PCfg(model="m", base_url="http://x", api_key="k2"), concurrency=4
    )
    c1 = await _get_cached_client(p1)
    c2 = await _get_cached_client(p2)
    assert c1 is not c2


@pytest.mark.asyncio
async def test_close_client_cache():
    """close_client_cache 清理所有缓存客户端."""
    provider = LLMProviderConfig(
        provider=PCfg(model="m", base_url="http://x", api_key="k"), concurrency=4
    )
    await _get_cached_client(provider)
    await close_client_cache()
    # After close, cache should be empty
    from app.models.chat import _client_cache

    assert len(_client_cache) == 0


@pytest.mark.asyncio
async def test_batch_generate_uses_provider_semaphore():
    """batch_generate 应通过 provider semaphore 控制并发."""
    provider = LLMProviderConfig(
        provider=PCfg(model="test-model", base_url="http://test", api_key="test"),
        temperature=0.0,
        concurrency=2,
    )
    model = ChatModel(providers=[provider])
    model.generate = AsyncMock(return_value="ok")
    results = await model.batch_generate(["a", "b", "c"])
    assert len(results) == 3
    assert model.generate.call_count == 3
