"""测试共享 fixtures 和清理函数."""

from contextlib import suppress

import app.memory.singleton
from app.models.chat import clear_semaphore_cache
from app.models.embedding import reset_embedding_singleton
from app.models.settings import LLMSettings


def reset_all_singletons() -> None:
    """重置所有全局单例状态以隔离测试."""
    reset_embedding_singleton()
    with suppress(AttributeError):
        LLMSettings.load.cache_clear()
    with suppress(AttributeError):
        clear_semaphore_cache()
    with suppress(AttributeError):
        app.memory.singleton._memory_store_state[0] = None
