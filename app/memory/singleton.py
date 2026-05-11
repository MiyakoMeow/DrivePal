"""记忆模块单例模块."""

import logging
import threading

from app.config import DATA_DIR
from app.memory.memory import MemoryModule
from app.models.chat import get_chat_model
from app.models.embedding import get_cached_embedding_model

logger = logging.getLogger(__name__)

_memory_module_state: list[MemoryModule | None] = [None]
_memory_module_lock = threading.Lock()


def get_memory_module() -> MemoryModule:
    """获取或初始化记忆模块单例."""
    if _memory_module_state[0] is None:
        with _memory_module_lock:
            if _memory_module_state[0] is None:
                _memory_module_state[0] = MemoryModule(
                    data_dir=DATA_DIR,
                    embedding_model=get_cached_embedding_model(),
                    chat_model=get_chat_model(),
                )
    return _memory_module_state[0]


async def close_memory_module() -> None:
    """关闭记忆模块单例（若已初始化）。

    幂等——未初始化时无操作。CLI 退出前调用以确保 FAISS 索引落盘。

    持锁原子读-清-释放，再异步关闭释放锁避免阻塞。
    """
    with _memory_module_lock:
        mm = _memory_module_state[0]
        if mm is None:
            return
        _memory_module_state[0] = None
    try:
        await mm.close()
    except Exception:
        logger.exception("Failed to close MemoryModule")
