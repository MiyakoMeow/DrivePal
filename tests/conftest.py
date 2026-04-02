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

    for provider in providers:
        if not provider.provider.base_url:
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
    return None


def is_llm_available() -> bool:
    """检查外部 LLM 是否已配置并可响应."""
    return get_available_provider() is not None


SKIP_IF_NO_LLM = pytest.mark.skipif(
    not is_llm_available(),
    reason="LLM API 不可用",
)


@pytest.fixture
def llm_provider() -> LLMProviderConfig | None:
    """返回可达的 LLM provider（若有），否则 None。"""
    return get_available_provider()
