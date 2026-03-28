"""Shared test configuration and fixtures."""

from functools import lru_cache

import pytest

from app.models.settings import LLMSettings


@lru_cache(maxsize=1)
def is_llm_available() -> bool:
    """Check whether an external LLM is configured and responding."""
    try:
        settings = LLMSettings.load()
    except RuntimeError:
        return False

    for provider in settings.llm_providers:
        if not provider.base_url:
            continue
        try:
            import requests

            resp = requests.get(
                f"{provider.base_url.rstrip('/v1')}/models",
                headers={"Authorization": f"Bearer {provider.api_key}"}
                if provider.api_key
                else {},
                timeout=5,
            )
            if resp.status_code == 200:
                return True
        except Exception:
            continue
    return False


SKIP_IF_NO_LLM = pytest.mark.skipif(
    not is_llm_available(),
    reason="LLM API not available",
)
