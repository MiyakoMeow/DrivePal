"""MemoryBankStore 单例模块。"""

import threading

from app.config import DATA_DIR
from app.memory.memory_bank import MemoryBankStore
from app.models.chat import get_chat_model
from app.models.embedding import get_cached_embedding_model

_memory_store_state: list[MemoryBankStore | None] = [None]
_memory_store_lock = threading.Lock()


def get_memory_store() -> MemoryBankStore:
    """获取或初始化 MemoryBankStore 单例。"""
    if _memory_store_state[0] is None:
        with _memory_store_lock:
            if _memory_store_state[0] is None:
                _memory_store_state[0] = MemoryBankStore(
                    data_dir=DATA_DIR,
                    embedding_model=get_cached_embedding_model(),
                    chat_model=get_chat_model(),
                )
    return _memory_store_state[0]
