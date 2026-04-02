"""共享测试配置和 fixtures."""

from functools import lru_cache

import pytest

from app.models.settings import LLMSettings, LLMProviderConfig


def _check_provider_reachable(provider: LLMProviderConfig) -> bool:
    """检查 provider 是否可达（发起真实 HTTP 请求）."""
    if not provider.provider.base_url:
        return True
    try:
        import requests
    except ImportError:
        return False

    try:
        base = provider.provider.base_url.rstrip("/")
        resp = requests.get(
            f"{base}/models",
            headers={"Authorization": f"Bearer {provider.provider.api_key}"}
            if provider.provider.api_key
            else {},
            timeout=5,
        )
        return resp.status_code == 200
    except requests.RequestException:
        return False


@lru_cache(maxsize=1)
def get_available_provider() -> LLMProviderConfig | None:
    """获取第一个可达的 LLM provider，或 None."""
    try:
        settings = LLMSettings.load()
    except RuntimeError:
        return None

    try:
        providers = settings.get_model_group_providers("default")
    except (KeyError, ValueError, RuntimeError):
        return None

    fallback_provider: LLMProviderConfig | None = None
    for provider in providers:
        if not provider.provider.base_url:
            fallback_provider = fallback_provider or provider
            continue
        if _check_provider_reachable(provider):
            return provider
    return fallback_provider


@pytest.fixture
def llm_provider() -> LLMProviderConfig | None:
    """返回可达的 LLM provider（若有），否则 None。"""
    return get_available_provider()


@pytest.fixture
def required_llm_provider(llm_provider: LLMProviderConfig | None) -> LLMProviderConfig:
    """返回可用 provider；不可用时直接 skip。"""
    if llm_provider is None:
        pytest.skip("No LLM provider available")
    return llm_provider
