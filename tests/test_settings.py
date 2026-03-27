"""Tests for model settings loader."""

import json
import os
import pytest

from app.models.settings import LLMSettings, LLMProviderConfig, EmbeddingProviderConfig


class TestLLMProviderConfig:
    def test_from_dict_full(self):
        cfg = LLMProviderConfig.from_dict(
            {
                "model": "gpt-4",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test",
                "temperature": 0.5,
            }
        )
        assert cfg.model == "gpt-4"
        assert cfg.base_url == "https://api.openai.com/v1"
        assert cfg.api_key == "sk-test"
        assert cfg.temperature == 0.5

    def test_from_dict_defaults(self):
        cfg = LLMProviderConfig.from_dict({"model": "test"})
        assert cfg.model == "test"
        assert cfg.base_url is None
        assert cfg.api_key is None
        assert cfg.temperature == 0.7


class TestEmbeddingProviderConfig:
    def test_from_dict_local(self):
        cfg = EmbeddingProviderConfig.from_dict(
            {
                "model": "BAAI/bge-small-zh-v1.5",
                "device": "cuda",
            }
        )
        assert cfg.model == "BAAI/bge-small-zh-v1.5"
        assert cfg.device == "cuda"
        assert cfg.base_url is None
        assert cfg.api_key is None

    def test_from_dict_remote(self):
        cfg = EmbeddingProviderConfig.from_dict(
            {
                "model": "text-embedding-3-small",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test",
            }
        )
        assert cfg.model == "text-embedding-3-small"
        assert cfg.base_url == "https://api.openai.com/v1"


class TestLLMSettingsLoad:
    def test_load_from_config_file(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config" / "llm.json"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            json.dumps(
                {
                    "llm": [
                        {
                            "model": "gpt-4",
                            "base_url": "https://api.openai.com/v1",
                            "api_key": "sk-a",
                        }
                    ],
                    "embedding": [{"model": "bge-test", "device": "cpu"}],
                }
            )
        )
        monkeypatch.chdir(tmp_path)
        settings = LLMSettings.load()
        assert len(settings.llm_providers) == 1
        assert settings.llm_providers[0].model == "gpt-4"
        assert len(settings.embedding_providers) == 1
        assert settings.embedding_providers[0].model == "bge-test"

    def test_load_fallback_to_env_vars(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        monkeypatch.setenv("OPENAI_MODEL", "gpt-4")
        settings = LLMSettings.load()
        assert len(settings.llm_providers) >= 1
        assert any(p.model == "gpt-4" for p in settings.llm_providers)

    def test_load_deepseek_env_as_final_fallback(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
        monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
        monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")
        settings = LLMSettings.load()
        assert any(p.model == "deepseek-chat" for p in settings.llm_providers)

    def test_load_no_config_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(RuntimeError, match="No LLM configuration found"):
            LLMSettings.load()

    def test_config_file_plus_env_merging(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config" / "llm.json"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            json.dumps(
                {
                    "llm": [
                        {
                            "model": "model-a",
                            "base_url": "https://a.com/v1",
                            "api_key": "sk-a",
                        }
                    ],
                    "embedding": [{"model": "bge-test"}],
                }
            )
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://openai.com/v1")
        monkeypatch.setenv("OPENAI_MODEL", "model-b")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
        monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://deepseek.com/v1")
        monkeypatch.setenv("DEEPSEEK_MODEL", "model-c")
        settings = LLMSettings.load()
        assert settings.llm_providers[0].model == "model-a"
        assert any(p.model == "model-b" for p in settings.llm_providers)
        assert any(p.model == "model-c" for p in settings.llm_providers)

    def test_dedup_providers(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config" / "llm.json"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            json.dumps(
                {
                    "llm": [
                        {
                            "model": "gpt-4",
                            "base_url": "https://api.openai.com/v1",
                            "api_key": "sk-a",
                        },
                        {
                            "model": "gpt-4",
                            "base_url": "https://api.openai.com/v1",
                            "api_key": "sk-b",
                        },
                    ],
                    "embedding": [],
                }
            )
        )
        monkeypatch.chdir(tmp_path)
        settings = LLMSettings.load()
        llm_models = [(p.model, p.base_url) for p in settings.llm_providers]
        assert len(llm_models) == len(set(llm_models))
