"""记忆模块单例模块."""

import threading

from app.config import DATA_DIR
from app.memory.memory import MemoryModule
from app.models._factories import get_chat_model
from app.models.embedding import get_cached_embedding_model

_memory_module: list[MemoryModule | None] = [None]
_memory_module_lock = threading.Lock()


def get_memory_module() -> MemoryModule:
    """获取或初始化记忆模块单例."""
    if _memory_module[0] is None:
        with _memory_module_lock:
            if _memory_module[0] is None:
                _memory_module[0] = MemoryModule(
                    data_dir=DATA_DIR,
                    embedding_model=get_cached_embedding_model(),
                    chat_model=get_chat_model(),
                )
    return _memory_module[0]
