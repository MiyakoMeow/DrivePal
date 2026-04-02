"""共享测试配置和 fixtures."""

from functools import lru_cache

import pytest


@lru_cache(maxsize=1)
def is_llm_available() -> bool:
    """检查 LLM 是否已配置并可响应."""
    try:
        from app.models.settings import get_chat_model

        model = get_chat_model()
        return model.is_available()
    except Exception:
        return False


SKIP_IF_NO_LLM = pytest.mark.skipif(
    not is_llm_available(),
    reason="LLM API 不可用",
)
