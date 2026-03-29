"""Tests for model settings loader."""

import json

import pytest
from unittest.mock import patch, MagicMock

from app.models.settings import (
    LLMSettings,
    LLMProviderConfig,
    EmbeddingProviderConfig,
    ProviderConfig,
)


class TestLLMProviderConfig:
    """Tests for LLMProviderConfig."""

    def test_from_dict_full(self):
        """Verify full dict parsing with all fields."""
        cfg = LLMProviderConfig.from_dict(
            {
                "model": "gpt-4",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test",
                "temperature": 0.5,
            }
        )
        assert cfg.provider.model == "gpt-4"
        assert cfg.provider.base_url == "https://api.openai.com/v1"
        assert cfg.provider.api_key == "sk-test"
        assert cfg.temperature == 0.5

    def test_from_dict_defaults(self):
        """Verify default values when optional fields are missing."""
        cfg = LLMProviderConfig.from_dict({"model": "test"})
        assert cfg.provider.model == "test"
        assert cfg.provider.base_url is None
        assert cfg.provider.api_key is None
        assert cfg.temperature == 0.7


class TestEmbeddingProviderConfig:
    """Tests for EmbeddingProviderConfig."""

    def test_from_dict_local(self):
        """Verify local HuggingFace provider parsing."""
        cfg = EmbeddingProviderConfig.from_dict(
            {
                "model": "BAAI/bge-small-zh-v1.5",
                "device": "cuda",
            }
        )
        assert cfg.provider.model == "BAAI/bge-small-zh-v1.5"
        assert cfg.device == "cuda"
        assert cfg.provider.base_url is None
        assert cfg.provider.api_key is None

    def test_from_dict_remote(self):
        """Verify remote OpenAI-compatible provider parsing."""
        cfg = EmbeddingProviderConfig.from_dict(
            {
                "model": "text-embedding-3-small",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test",
            }
        )
        assert cfg.provider.model == "text-embedding-3-small"
        assert cfg.provider.base_url == "https://api.openai.com/v1"


class TestLLMSettingsLoad:
    """Tests for LLMSettings.load configuration loading."""

    def test_load_from_config_file(self, tmp_path, monkeypatch):
        """Verify loading providers from config/llm.json."""
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
        assert settings.llm_providers[0].provider.model == "gpt-4"
        assert len(settings.embedding_providers) == 1
        assert settings.embedding_providers[0].provider.model == "bge-test"

    def test_load_fallback_to_env_vars(self, tmp_path, monkeypatch):
        """Verify OPENAI_XXX env vars are used when config file is absent."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        monkeypatch.setenv("OPENAI_MODEL", "gpt-4")
        settings = LLMSettings.load()
        assert len(settings.llm_providers) >= 1
        assert any(p.provider.model == "gpt-4" for p in settings.llm_providers)

    def test_load_deepseek_env_as_final_fallback(self, tmp_path, monkeypatch):
        """Verify DEEPSEEK_XXX env vars are used when OPENAI_XXX are absent."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
        monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
        monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")
        settings = LLMSettings.load()
        assert any(p.provider.model == "deepseek-chat" for p in settings.llm_providers)

    def test_load_no_config_raises(self, tmp_path, monkeypatch):
        """Verify RuntimeError when no LLM config is available."""
        monkeypatch.chdir(tmp_path)
        with pytest.raises(RuntimeError, match="No LLM configuration found"):
            LLMSettings.load()

    def test_config_file_plus_env_merging(self, tmp_path, monkeypatch):
        """Verify config file providers come before env var providers."""
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
        assert settings.llm_providers[0].provider.model == "model-a"
        assert any(p.provider.model == "model-b" for p in settings.llm_providers)
        assert any(p.provider.model == "model-c" for p in settings.llm_providers)

    def test_dedup_providers(self, tmp_path, monkeypatch):
        """Verify duplicate providers are deduplicated by model+base_url."""
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
        llm_models = [
            (p.provider.model, p.provider.base_url) for p in settings.llm_providers
        ]
        assert len(llm_models) == len(set(llm_models))


class TestChatModelFallback:
    """Tests for ChatModel multi-provider fallback behavior."""

    def test_generate_with_single_provider(self):
        """Verify single provider generates successfully."""
        from app.models.chat import ChatModel
        from app.models.settings import LLMProviderConfig

        providers = [
            LLMProviderConfig(
                provider=ProviderConfig(
                    model="test-model",
                    base_url="http://fake:8000/v1",
                    api_key="sk-test",
                ),
            )
        ]
        chat = ChatModel(providers=providers)
        with patch.object(chat, "_invoke_provider", return_value="response"):
            result = chat.generate("hello")
        assert result == "response"

    def test_generate_falls_back_on_error(self):
        """Verify fallback to next provider when the first fails."""
        from app.models.chat import ChatModel
        from app.models.settings import LLMProviderConfig

        providers = [
            LLMProviderConfig(
                provider=ProviderConfig(
                    model="bad-model", base_url="http://fake1:8000/v1", api_key="sk-bad"
                ),
            ),
            LLMProviderConfig(
                provider=ProviderConfig(
                    model="good-model",
                    base_url="http://fake2:8000/v1",
                    api_key="sk-good",
                ),
            ),
        ]
        chat = ChatModel(providers=providers)
        call_count = 0

        def mock_invoke(provider, messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("API error")
            return "fallback response"

        with patch.object(chat, "_invoke_provider", side_effect=mock_invoke):
            result = chat.generate("hello")
        assert result == "fallback response"
        assert call_count == 2

    def test_generate_all_providers_fail_raises(self):
        """Verify RuntimeError when all providers fail."""
        from app.models.chat import ChatModel
        from app.models.settings import LLMProviderConfig

        providers = [
            LLMProviderConfig(
                provider=ProviderConfig(
                    model="bad1", base_url="http://fake1:8000/v1", api_key="sk-1"
                ),
            ),
            LLMProviderConfig(
                provider=ProviderConfig(
                    model="bad2", base_url="http://fake2:8000/v1", api_key="sk-2"
                ),
            ),
        ]
        chat = ChatModel(providers=providers)

        with patch.object(chat, "_invoke_provider", side_effect=RuntimeError("fail")):
            with pytest.raises(RuntimeError, match="All LLM providers failed"):
                chat.generate("hello")


class TestEmbeddingModelFallback:
    """Tests for EmbeddingModel multi-provider fallback behavior."""

    def test_local_provider_creates_huggingface(self):
        """Verify local provider uses HuggingFaceEmbeddings."""
        from app.models.embedding import EmbeddingModel
        from app.models.settings import EmbeddingProviderConfig

        providers = [
            EmbeddingProviderConfig(
                provider=ProviderConfig(model="fake-model"), device="cpu"
            )
        ]
        emb = EmbeddingModel(providers=providers)
        with patch("app.models.embedding.HuggingFaceEmbeddings") as mock_cls:
            mock_cls.return_value = MagicMock()
            _ = emb.client
        mock_cls.assert_called_once_with(
            model_name="fake-model",
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )

    def test_remote_provider_creates_openai(self):
        """Verify remote provider uses OpenAIEmbeddings."""
        from app.models.embedding import EmbeddingModel
        from app.models.settings import EmbeddingProviderConfig

        providers = [
            EmbeddingProviderConfig(
                provider=ProviderConfig(
                    model="text-embedding-3-small",
                    base_url="https://api.openai.com/v1",
                    api_key="sk-test",
                ),
            )
        ]
        emb = EmbeddingModel(providers=providers)
        with patch("app.models.embedding.OpenAIEmbeddings") as mock_cls:
            mock_cls.return_value = MagicMock()
            _ = emb.client
        mock_cls.assert_called_once()

    def test_fallback_to_next_provider(self):
        """Verify fallback when first embedding provider fails to load."""
        from app.models.embedding import EmbeddingModel
        from app.models.settings import EmbeddingProviderConfig

        providers = [
            EmbeddingProviderConfig(
                provider=ProviderConfig(model="bad-model"), device="cpu"
            ),
            EmbeddingProviderConfig(
                provider=ProviderConfig(model="good-model"), device="cpu"
            ),
        ]
        emb = EmbeddingModel(providers=providers)

        call_count = 0

        def mock_hf(model_name, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("load failed")
            return MagicMock()

        with patch("app.models.embedding.HuggingFaceEmbeddings", side_effect=mock_hf):
            _ = emb.client
        assert call_count == 2

    def test_encode_uses_client(self):
        """Verify encode delegates to the cached client."""
        from app.models.embedding import EmbeddingModel
        from app.models.settings import EmbeddingProviderConfig

        providers = [
            EmbeddingProviderConfig(
                provider=ProviderConfig(model="fake-model"), device="cpu"
            )
        ]
        emb = EmbeddingModel(providers=providers)
        mock_client = MagicMock()
        mock_client.embed_query.return_value = [0.1, 0.2, 0.3]
        emb._client = mock_client
        result = emb.encode("test")
        assert result == [0.1, 0.2, 0.3]


def test_judge_provider_config_from_dict():
    """Test JudgeProviderConfig.from_dict creates correct config."""
    from app.models.settings import JudgeProviderConfig

    d = {
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "sk-xxx",
        "temperature": 0.1,
    }
    cfg = JudgeProviderConfig.from_dict(d)
    assert cfg.provider.model == "deepseek-chat"
    assert cfg.provider.base_url == "https://api.deepseek.com/v1"
    assert cfg.provider.api_key == "sk-xxx"
    assert cfg.temperature == 0.1


def test_judge_provider_config_defaults():
    """Test JudgeProviderConfig defaults are applied correctly."""
    from app.models.settings import JudgeProviderConfig

    cfg = JudgeProviderConfig.from_dict({"model": "test"})
    assert cfg.provider.base_url is None
    assert cfg.provider.api_key is None
    assert cfg.temperature == 0.1


def test_llm_settings_loads_judge(tmp_path, monkeypatch):
    """Test LLMSettings loads judge provider from config."""
    from app.models.settings import LLMSettings
    import json

    config = {
        "llm": [{"model": "qwen", "base_url": "http://localhost:8000/v1"}],
        "judge": {"model": "deepseek-chat", "base_url": "https://api.deepseek.com/v1"},
    }
    config_file = tmp_path / "llm.json"
    config_file.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr("app.models.settings.CONFIG_PATH", str(config_file))

    settings = LLMSettings.load()
    assert settings.judge_provider is not None
    assert settings.judge_provider.provider.model == "deepseek-chat"
