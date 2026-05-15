"""测试共享 fixtures 和清理函数."""

from contextlib import suppress

import app.memory.singleton
from app.models.chat import clear_semaphore_cache
from app.models.embedding import reset_embedding_singleton
from app.models.settings import LLMSettings

# 需 patch DATA_DIR 的模块列表（用于 app_client/client fixture 数据隔离）
MODULES_WITH_DATA_DIR = [
    "app.config",
    "app.api.main",
    "app.memory.singleton",
    "app.api.v1.query",
    "app.api.v1.ws",
]
MODULES_WITH_DATA_ROOT = ["app.config"]


def reset_all_singletons() -> None:
    """重置所有全局单例状态以隔离测试."""
    reset_embedding_singleton()
    with suppress(AttributeError):
        LLMSettings.load.cache_clear()
    with suppress(AttributeError):
        clear_semaphore_cache()
    with suppress(AttributeError):
        app.memory.singleton._memory_module_state[0] = None
