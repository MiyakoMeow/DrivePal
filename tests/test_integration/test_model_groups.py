"""model_groups 集成测试."""

import tomli_w
from pathlib import Path

import pytest


def test_model_groups_basic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """测试基本的 model_groups 配置."""
    config = {
        "model_groups": {
            "smart": {"models": ["deepseek/deepseek-chat"]},
        },
        "model_providers": {
            "deepseek": {
                "base_url": "https://api.deepseek.com/v1",
                "api_key_env": "DEEPSEEK_API_KEY",
            },
        },
    }
    config_file = tmp_path / "llm.toml"
    config_file.write_bytes(tomli_w.dumps(config).encode())
    monkeypatch.setenv("CONFIG_PATH", str(config_file))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")

    from adapters.model_config import _load_config, get_model_group_providers

    _load_config.cache_clear()

    providers = get_model_group_providers("smart")
    assert len(providers) == 1
    assert providers[0]["model"] == "deepseek-chat"
    assert providers[0]["base_url"] == "https://api.deepseek.com/v1"


def test_model_groups_with_query_params(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """测试带 query 参数的 model_groups."""
    config = {
        "model_groups": {
            "fast": {"models": ["zhipuai-coding-plan/glm-4.7-flashx?temperature=0.1"]},
        },
        "model_providers": {
            "zhipuai-coding-plan": {
                "base_url": "https://open.bigmodel.cn/api/paas/v4",
                "api_key_env": "ZHIPU_API_KEY",
            },
        },
    }
    config_file = tmp_path / "llm.toml"
    config_file.write_bytes(tomli_w.dumps(config).encode())
    monkeypatch.setenv("CONFIG_PATH", str(config_file))
    monkeypatch.setenv("ZHIPU_API_KEY", "sk-test")

    from adapters.model_config import _load_config, get_model_group_providers

    _load_config.cache_clear()

    providers = get_model_group_providers("fast")
    assert len(providers) == 1
    assert providers[0]["model"] == "glm-4.7-flashx"
    assert providers[0]["temperature"] == 0.1


def test_model_groups_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """测试不存在的 model_group."""
    config = {"model_groups": {}}
    config_file = tmp_path / "llm.toml"
    config_file.write_bytes(tomli_w.dumps(config).encode())
    monkeypatch.setenv("CONFIG_PATH", str(config_file))

    from adapters.model_config import _load_config, get_model_group_providers

    _load_config.cache_clear()

    with pytest.raises(KeyError):
        get_model_group_providers("nonexistent")


def test_empty_model_group_returns_empty_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """测试空 model_group 返回空列表."""
    config = {
        "model_groups": {
            "empty": {"models": []},
        },
    }
    config_file = tmp_path / "llm.toml"
    config_file.write_bytes(tomli_w.dumps(config).encode())
    monkeypatch.setenv("CONFIG_PATH", str(config_file))

    from adapters.model_config import _load_config, get_model_group_providers

    _load_config.cache_clear()

    providers = get_model_group_providers("empty")
    assert providers == []
