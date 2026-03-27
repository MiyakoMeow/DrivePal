import urllib.request
import urllib.error


def is_vllm_available() -> bool:
    try:
        req = urllib.request.Request("http://localhost:8000/v1/models", method="GET")
        with urllib.request.urlopen(req, timeout=3):
            return True
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def is_vllm_unavailable() -> bool:
    return not is_vllm_available()
