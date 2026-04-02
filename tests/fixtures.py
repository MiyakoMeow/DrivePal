"""Test shared fixtures and cleanup functions."""

from contextlib import suppress

from app.models.embedding import reset_embedding_singleton


def reset_all_singletons() -> None:
    """Reset all global singleton states for test isolation."""
    import app.models.settings
    import app.api.main

    reset_embedding_singleton()
    with suppress(AttributeError):
        app.models.settings._settings_cache = None
    with suppress(AttributeError):
        app.api.main._memory_module = None
