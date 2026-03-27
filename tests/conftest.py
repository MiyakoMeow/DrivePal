"""Shared test configuration and fixtures."""

import os


def is_llm_available() -> bool:
    """Check whether an external LLM is configured via environment variables."""
    return bool(os.environ.get("OPENAI_MODEL"))
