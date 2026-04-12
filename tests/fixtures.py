"""测试共享 fixtures 和清理函数."""

from contextlib import suppress

import app.memory.singleton
import app.models.chat
from app.models.embedding import reset_embedding_singleton


def reset_all_singletons() -> None:
    """重置所有全局单例状态以隔离测试."""
    reset_embedding_singleton()
    with suppress(AttributeError):
        app.models.chat._get_settings_once.cache_clear()
    with suppress(AttributeError):
        app.models.chat._get_lock.cache_clear()
    with suppress(AttributeError):
        app.models.chat._semaphore_cache.clear()
    with suppress(AttributeError):
        app.memory.singleton._memory_module_state[0] = None
