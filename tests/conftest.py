"""Shared test configuration and fixtures."""

import os
import urllib.request
import urllib.error

_DEFAULT_VLLM_BASE_URL = "http://localhost:8000/v1"


def _get_vllm_base_url() -> str:
    return os.getenv("VLLM_BASE_URL", _DEFAULT_VLLM_BASE_URL)


def is_vllm_available() -> bool:
    """Check whether the vLLM server is reachable."""
    base_url = _get_vllm_base_url()
    models_url = f"{base_url}/models"
    try:
        req = urllib.request.Request(models_url, method="GET")
        with urllib.request.urlopen(req, timeout=3):
            return True
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def is_vllm_unavailable() -> bool:
    """Check whether the vLLM server is not reachable."""
    return not is_vllm_available()
