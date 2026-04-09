"""model_config 模块测试."""

import tomli_w

import pytest
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def clear_config_cache() -> None:
    """清理配置缓存的 fixture."""
    from vendor_adapter.VehicleMemBench.model_config import (
        _load_config,
        get_benchmark_client,
        get_benchmark_config,
    )

    _load_config.cache_clear()
    get_benchmark_config.cache_clear()
    get_benchmark_client.cache_clear()


def test_get_benchmark_client_returns_openai_instance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clear_config_cache: None
) -> None:
    """测试 get_benchmark_client 从 model_groups.benchmark 返回 OpenAI 实例."""
    config = {
        "model_groups": {
            "benchmark": {"models": ["test-provider/test-model?temperature=0.0"]},
        },
        "model_providers": {
            "test-provider": {
                "base_url": "http://localhost:1234/v1",
                "api_key": "test",
            },
        },
    }
    config_file = tmp_path / "llm.toml"
    config_file.write_bytes(tomli_w.dumps(config).encode())
    monkeypatch.setenv("CONFIG_PATH", str(config_file))
    from vendor_adapter.VehicleMemBench.model_config import get_benchmark_client

    client = get_benchmark_client()
    assert client is not None
    assert hasattr(client, "chat")


def test_get_benchmark_client_uses_model_groups_benchmark(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clear_config_cache: None
) -> None:
    """测试 get_benchmark_client 使用 model_groups.benchmark 配置."""
    config = {
        "model_groups": {
            "benchmark": {"models": ["minimax-cn/MiniMax-M2.7?temperature=0.0"]},
        },
        "model_providers": {
            "minimax-cn": {
                "base_url": "https://api.minimaxi.com/v1",
                "api_key_env": "TEST_API_KEY",
            },
        },
    }
    monkeypatch.setenv("TEST_API_KEY", "sk-test123")
    config_file = tmp_path / "llm.toml"
    config_file.write_bytes(tomli_w.dumps(config).encode())
    monkeypatch.setenv("CONFIG_PATH", str(config_file))
    from vendor_adapter.VehicleMemBench.model_config import get_benchmark_client

    client = get_benchmark_client()
    assert client is not None


def test_get_benchmark_client_raises_error_without_benchmark_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clear_config_cache: None
) -> None:
    """测试无 model_groups.benchmark 时 get_benchmark_client 抛出错误."""
    config = {
        "model_groups": {
            "default": {"models": ["local/qwen3.5-2b"]},
        },
        "model_providers": {
            "local": {
                "base_url": "http://127.0.0.1:50721/v1",
                "api_key": "none",
            },
        },
    }
    config_file = tmp_path / "llm.toml"
    config_file.write_bytes(tomli_w.dumps(config).encode())
    monkeypatch.setenv("CONFIG_PATH", str(config_file))
    from vendor_adapter.VehicleMemBench.model_config import get_benchmark_client

    with pytest.raises(ValueError, match="model_groups.benchmark must be configured"):
        get_benchmark_client()


def test_get_store_chat_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clear_config_cache: None
) -> None:
    """测试 get_store_chat_model 返回聊天模型."""
    config = {
        "model_groups": {
            "default": {"models": ["local/qwen3.5-2b"]},
        },
        "model_providers": {
            "local": {
                "base_url": "http://127.0.0.1:50721",
                "api_key": "none",
            },
        },
    }
    config_file = tmp_path / "llm.toml"
    config_file.write_bytes(tomli_w.dumps(config).encode())
    monkeypatch.setenv("CONFIG_PATH", str(config_file))
    from vendor_adapter.VehicleMemBench.model_config import get_store_chat_model

    model = get_store_chat_model()
    assert model is not None


def test_resolve_model_string_simple() -> None:
    """测试简单模型引用解析."""
    from app.models.model_string import resolve_model_string

    result = resolve_model_string("deepseek/deepseek-chat")
    assert result.provider_name == "deepseek"
    assert result.model_name == "deepseek-chat"
    assert result.params == {}


def test_resolve_model_string_with_params() -> None:
    """测试带参数的模型引用解析."""
    from app.models.model_string import resolve_model_string

    result = resolve_model_string(
        "zhipuai-coding-plan/glm-4.7-flashx?temperature=0.1&max_tokens=1000"
    )
    assert result.provider_name == "zhipuai-coding-plan"
    assert result.model_name == "glm-4.7-flashx"
    assert result.params == {"temperature": 0.1, "max_tokens": 1000}


def test_resolve_model_string_invalid_format() -> None:
    """测试无效格式."""
    from app.models.model_string import resolve_model_string

    with pytest.raises(ValueError, match="Invalid model string format"):
        resolve_model_string("invalid-format")
