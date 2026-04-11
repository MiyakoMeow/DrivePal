"""测试共享 fixtures 和清理函数."""

from contextlib import suppress

import app.memory.singleton
import app.models._factories
from app.models.embedding import reset_embedding_singleton


def reset_all_singletons() -> None:
    """重置所有全局单例状态以隔离测试."""
    reset_embedding_singleton()
    with suppress(AttributeError):
        app.models._factories._settings_cache[0] = None
    with suppress(AttributeError):
        app.memory.singleton._memory_module[0] = None
