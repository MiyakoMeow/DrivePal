"""Shared test configuration and fixtures."""

import os


def is_llm_available() -> bool:
    """Check whether an external LLM is configured."""
    return bool(
        os.environ.get("OPENAI_MODEL")
        or os.environ.get("DEEPSEEK_MODEL")
        or os.path.exists(os.path.join(os.getcwd(), "config", "llm.json"))
    )
