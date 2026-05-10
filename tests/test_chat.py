"""ChatModel 客户端缓存测试."""

import pytest

from app.models.chat import (
    _get_cached_client,
    clear_semaphore_cache,
    close_client_cache,
)
from app.models.settings import LLMProviderConfig
from app.models.types import ProviderConfig as PCfg


@pytest.fixture(autouse=True)
def _clean_cache():
    """每个测试前后清理客户端缓存"""
    clear_semaphore_cache()
    yield
    clear_semaphore_cache()


@pytest.mark.asyncio
async def test_cached_client_reuse():
    """同 base_url+api_key 返回同一 AsyncOpenAI 实例"""
    provider = LLMProviderConfig(
        provider=PCfg(model="m", base_url="http://x", api_key="k"), concurrency=4
    )
    c1 = await _get_cached_client(provider)
    c2 = await _get_cached_client(provider)
    assert c1 is c2


@pytest.mark.asyncio
async def test_cached_client_different_keys():
    """不同 api_key 返回不同实例"""
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
    """close_client_cache 清理所有缓存客户端"""
    provider = LLMProviderConfig(
        provider=PCfg(model="m", base_url="http://x", api_key="k"), concurrency=4
    )
    await _get_cached_client(provider)
    await close_client_cache()
    # After close, cache should be empty
    from app.models.chat import _client_cache

    assert len(_client_cache) == 0
