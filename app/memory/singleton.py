"""记忆模块单例模块."""

from app.config import DATA_DIR
from app.memory.memory import MemoryModule
from app.models.embedding import get_cached_embedding_model
from app.models.settings import get_chat_model

_memory_module: MemoryModule | None = None


def get_memory_module() -> MemoryModule:
    """获取或初始化记忆模块单例."""
    global _memory_module  # noqa: PLW0603
    if _memory_module is None:
        _memory_module = MemoryModule(
            data_dir=DATA_DIR,
            embedding_model=get_cached_embedding_model(),
            chat_model=get_chat_model(),
        )
    return _memory_module
