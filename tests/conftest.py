"""共享测试配置和 fixtures."""

from functools import lru_cache

import pytest

from app.models.settings import LLMSettings, LLMProviderConfig


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
        try:
            import requests

            base = provider.provider.base_url.rstrip("/")
            if base.endswith("/v1"):
                base = base[:-3]
            resp = requests.get(
                f"{base}/models",
                headers={"Authorization": f"Bearer {provider.provider.api_key}"}
                if provider.provider.api_key
                else {},
                timeout=5,
            )
            if resp.status_code == 200:
                return provider
        except Exception:
            continue
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
