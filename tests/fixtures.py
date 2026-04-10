"""测试共享 fixtures 和清理函数."""

from contextlib import suppress

from app.models.embedding import reset_embedding_singleton


def reset_all_singletons() -> None:
    """重置所有全局单例状态以隔离测试."""
    import app.api.main
    import app.models.settings

    reset_embedding_singleton()
    with suppress(AttributeError):
        app.models.settings._settings_cache = None
    with suppress(AttributeError):
        app.api.main._memory_module = None
