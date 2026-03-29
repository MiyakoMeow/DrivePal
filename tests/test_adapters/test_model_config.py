"""model_config 模块测试."""

import json


def test_get_benchmark_client_returns_openai_instance(tmp_path, monkeypatch):
    """Test get_benchmark_client returns an OpenAI instance."""
    config = {
        "llm": [
            {
                "model": "test-model",
                "base_url": "http://localhost:1234/v1",
                "api_key": "test",
            }
        ],
        "embedding": [{"model": "BAAI/bge-small-zh-v1.5", "device": "cpu"}],
    }
    config_file = tmp_path / "llm.json"
    config_file.write_text(json.dumps(config))
    monkeypatch.setattr("adapters.model_config.CONFIG_PATH", str(config_file))
    from adapters.model_config import get_benchmark_client

    client = get_benchmark_client()
    assert client is not None
    assert hasattr(client, "chat")


def test_get_benchmark_client_uses_llm_config_when_no_benchmark(tmp_path, monkeypatch):
    """Test get_benchmark_client uses LLM config when no benchmark config exists."""
    config = {
        "llm": [
            {
                "model": "qwen3.5-2b",
                "base_url": "http://127.0.0.1:50721/v1",
                "api_key": "none",
            }
        ],
        "embedding": [{"model": "BAAI/bge-small-zh-v1.5", "device": "cpu"}],
    }
    config_file = tmp_path / "llm.json"
    config_file.write_text(json.dumps(config))
    monkeypatch.setattr("adapters.model_config.CONFIG_PATH", str(config_file))
    from adapters.model_config import get_benchmark_client

    client = get_benchmark_client()
    assert client is not None


def test_get_benchmark_client_uses_benchmark_config_with_env(tmp_path, monkeypatch):
    """Test get_benchmark_client uses benchmark config with environment variable."""
    monkeypatch.setenv("TEST_API_KEY", "sk-test123")
    config = {
        "llm": [
            {
                "model": "qwen3.5-2b",
                "base_url": "http://127.0.0.1:50721/v1",
                "api_key": "none",
            }
        ],
        "benchmark": {
            "model": "MiniMax-M2.7",
            "base_url": "https://api.minimaxi.com/v1",
            "api_key_env": "TEST_API_KEY",
            "temperature": 0.0,
            "max_tokens": 8192,
        },
        "embedding": [{"model": "BAAI/bge-small-zh-v1.5", "device": "cpu"}],
    }
    config_file = tmp_path / "llm.json"
    config_file.write_text(json.dumps(config))
    monkeypatch.setattr("adapters.model_config.CONFIG_PATH", str(config_file))
    from adapters.model_config import get_benchmark_client

    client = get_benchmark_client()
    assert client is not None


def test_get_store_chat_model(tmp_path, monkeypatch):
    """Test get_store_chat_model returns a chat model."""
    config = {
        "llm": [
            {
                "model": "qwen3.5-2b",
                "base_url": "http://127.0.0.1:50721/v1",
                "api_key": "none",
            }
        ],
        "embedding": [{"model": "BAAI/bge-small-zh-v1.5", "device": "cpu"}],
    }
    config_file = tmp_path / "llm.json"
    config_file.write_text(json.dumps(config))
    monkeypatch.setattr("adapters.model_config.CONFIG_PATH", str(config_file))
    from adapters.model_config import get_store_chat_model

    model = get_store_chat_model()
    assert model is not None
