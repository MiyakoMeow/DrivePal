"""模型设置加载器测试."""

from pathlib import Path

import pytest
import tomli_w
from unittest.mock import patch, MagicMock, AsyncMock

from app.models.settings import (
    LLMSettings,
    LLMProviderConfig,
    EmbeddingProviderConfig,
    ProviderConfig,
)


class TestLLMProviderConfig:
    """LLMProviderConfig 测试."""

    def test_from_dict_full(self) -> None:
        """验证包含所有字段的完整字典解析."""
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

    def test_from_dict_defaults(self) -> None:
        """验证可选字段缺失时的默认值."""
        cfg = LLMProviderConfig.from_dict({"model": "test"})
        assert cfg.provider.model == "test"
        assert cfg.provider.base_url is None
        assert cfg.provider.api_key is None
        assert cfg.temperature == 0.7

    def test_from_dict_with_type(self) -> None:
        """验证 from_dict 正确解析 type 字段."""
        cfg = LLMProviderConfig.from_dict(
            {
                "model": "Qwen/Qwen3.5-2B",
                "type": "vllm",
                "temperature": 0.7,
            }
        )
        assert cfg.type == "vllm"
        assert cfg.provider.model == "Qwen/Qwen3.5-2B"


class TestEmbeddingProviderConfig:
    """EmbeddingProviderConfig 测试."""

    def test_from_dict_local(self) -> None:
        """验证本地 HuggingFace 提供者解析."""
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

    def test_from_dict_remote(self) -> None:
        """验证远程 OpenAI 兼容提供者解析."""
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
    """LLMSettings.load 配置加载测试."""

    def test_load_from_config_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """验证从 config/llm.toml 加载提供者."""
        config_file = tmp_path / "config" / "llm.toml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            tomli_w.dumps(
                {
                    "model_groups": {
                        "default": {"models": ["openai/gpt-4"]},
                    },
                    "model_providers": {
                        "openai": {
                            "base_url": "https://api.openai.com/v1",
                            "api_key": "sk-a",
                        },
                        "huggingface": {},
                    },
                    "embedding": {"model": "huggingface/bge-test"},
                }
            )
        )
        monkeypatch.setenv("CONFIG_PATH", str(config_file))
        settings = LLMSettings.load()
        assert "default" in settings.model_groups
        assert settings.embedding_model == "huggingface/bge-test"

    def test_load_no_config_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """验证无 LLM 配置时抛出 RuntimeError."""
        monkeypatch.setenv("CONFIG_PATH", str(tmp_path / "nonexistent.toml"))
        with pytest.raises(RuntimeError, match="No LLM configuration found"):
            LLMSettings.load()

    def test_get_embedding_provider_local(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """验证 get_embedding_provider 解析本地 embedding 模型."""
        config = {
            "model_groups": {"default": {"models": ["local/qwen"]}},
            "model_providers": {
                "local": {"base_url": "http://localhost:8000", "api_key": "none"},
                "huggingface": {},
            },
            "embedding": {"model": "huggingface/BAAI/bge-small-zh-v1.5"},
        }
        config_file = tmp_path / "llm.toml"
        config_file.write_text(tomli_w.dumps(config))
        monkeypatch.setenv("CONFIG_PATH", str(config_file))
        from adapters.model_config import _load_config

        _load_config.cache_clear()
        settings = LLMSettings.load()
        provider = settings.get_embedding_provider()
        assert provider is not None
        assert provider.provider.model == "BAAI/bge-small-zh-v1.5"
        assert provider.provider.base_url is None
        _load_config.cache_clear()

    def test_get_embedding_provider_remote(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """验证 get_embedding_provider 解析远程 embedding 模型."""
        config = {
            "model_groups": {"default": {"models": ["local/qwen"]}},
            "model_providers": {
                "local": {"base_url": "http://localhost:8000", "api_key": "none"},
                "openai": {
                    "base_url": "https://api.openai.com/v1",
                    "api_key_env": "OPENAI_API_KEY",
                },
            },
            "embedding": {"model": "openai/text-embedding-3-small"},
        }
        config_file = tmp_path / "llm.toml"
        config_file.write_text(tomli_w.dumps(config))
        monkeypatch.setenv("CONFIG_PATH", str(config_file))
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        from adapters.model_config import _load_config

        _load_config.cache_clear()
        settings = LLMSettings.load()
        provider = settings.get_embedding_provider()
        assert provider is not None
        assert provider.provider.model == "text-embedding-3-small"
        assert provider.provider.base_url == "https://api.openai.com/v1"
        _load_config.cache_clear()

    def test_get_embedding_provider_with_device_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """验证 get_embedding_provider 解析 device 参数."""
        config = {
            "model_groups": {"default": {"models": ["local/qwen"]}},
            "model_providers": {
                "local": {"base_url": "http://localhost:8000", "api_key": "none"},
                "huggingface": {},
            },
            "embedding": {"model": "huggingface/BAAI/bge-small-zh-v1.5?device=cuda"},
        }
        config_file = tmp_path / "llm.toml"
        config_file.write_text(tomli_w.dumps(config))
        monkeypatch.setenv("CONFIG_PATH", str(config_file))
        from adapters.model_config import _load_config

        _load_config.cache_clear()
        settings = LLMSettings.load()
        provider = settings.get_embedding_provider()
        assert provider is not None
        assert provider.device == "cuda"
        _load_config.cache_clear()

    def test_get_embedding_provider_none_when_not_configured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """验证无 embedding 配置时返回 None."""
        config = {
            "model_groups": {"default": {"models": ["local/qwen"]}},
            "model_providers": {
                "local": {"base_url": "http://localhost:8000", "api_key": "none"},
            },
        }
        config_file = tmp_path / "llm.toml"
        config_file.write_text(tomli_w.dumps(config))
        monkeypatch.setenv("CONFIG_PATH", str(config_file))
        from adapters.model_config import _load_config

        _load_config.cache_clear()
        settings = LLMSettings.load()
        assert settings.get_embedding_provider() is None
        _load_config.cache_clear()

    def test_load_with_model_groups(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """验证从 model_groups 加载配置."""
        config_file = tmp_path / "config" / "llm.toml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            tomli_w.dumps(
                {
                    "model_groups": {
                        "default": {"models": ["openai/gpt-4"]},
                    },
                    "model_providers": {
                        "openai": {
                            "base_url": "https://api.openai.com/v1",
                            "api_key": "sk-a",
                        },
                    },
                }
            )
        )
        monkeypatch.setenv("CONFIG_PATH", str(config_file))
        from adapters.model_config import _load_config

        _load_config.cache_clear()
        settings = LLMSettings.load()
        assert "default" in settings.model_groups
        providers = settings.get_model_group_providers("default")
        assert len(providers) == 1
        assert providers[0].provider.model == "gpt-4"
        _load_config.cache_clear()

    def test_get_model_group_providers_vllm_type(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """验证 get_model_group_providers 正确解析 vllm 类型的提供者."""
        config_file = tmp_path / "llm.toml"
        config_file.write_text(
            tomli_w.dumps(
                {
                    "model_groups": {"default": {"models": ["local/qwen3.5-2b"]}},
                    "model_providers": {
                        "local": {
                            "type": "vllm",
                            "model": "Qwen/Qwen3.5-2B",
                            "tensor_parallel_size": 1,
                        },
                    },
                }
            )
        )
        monkeypatch.setenv("CONFIG_PATH", str(config_file))
        from adapters.model_config import _load_config

        _load_config.cache_clear()
        settings = LLMSettings.load()
        providers = settings.get_model_group_providers("default")
        assert len(providers) == 1
        assert providers[0].type == "vllm"
        assert providers[0].provider.model == "Qwen/Qwen3.5-2B"
        assert "tensor_parallel_size" in providers[0].extra
        _load_config.cache_clear()


class TestChatModelFallback:
    """ChatModel 多提供者回退行为测试."""

    async def test_generate_with_single_provider(self) -> None:
        """验证单个提供者成功生成."""
        from app.models.chat import ChatModel

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
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "response"
        with patch.object(chat, "_create_async_client") as mock_create:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_create.return_value = mock_client
            result = await chat.generate("hello")
        assert result == "response"

    async def test_generate_falls_back_on_error(self) -> None:
        """验证第一个失败时回退到下一个提供者."""
        from app.models.chat import ChatModel

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

        def mock_create(provider: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                client = MagicMock()
                client.chat.completions.create = AsyncMock(
                    side_effect=RuntimeError("API error")
                )
                return client
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "fallback response"
            client = MagicMock()
            client.chat.completions.create = AsyncMock(return_value=mock_response)
            return client

        with patch.object(chat, "_create_async_client", side_effect=mock_create):
            result = await chat.generate("hello")
        assert result == "fallback response"
        assert call_count == 2

    async def test_generate_all_providers_fail_raises(self) -> None:
        """验证所有提供者失败时抛出 RuntimeError."""
        from app.models.chat import ChatModel

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
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("fail")
        )

        with (
            patch.object(chat, "_create_async_client", return_value=mock_client),
            pytest.raises(RuntimeError, match="All LLM providers failed"),
        ):
            await chat.generate("hello")


class TestEmbeddingModelFallback:
    """EmbeddingModel 单提供者测试."""

    def test_local_provider_creates_sentence_transformer(self) -> None:
        """验证本地提供者使用 SentenceTransformer."""
        from app.models.embedding import EmbeddingModel

        provider = EmbeddingProviderConfig(
            provider=ProviderConfig(model="fake-model"), device="cpu"
        )
        emb = EmbeddingModel(provider=provider)
        mock_st = MagicMock()
        with patch(
            "sentence_transformers.SentenceTransformer", return_value=mock_st
        ) as mock_cls:
            _ = emb.client
        mock_cls.assert_called_once_with("fake-model", device="cpu")

    def test_remote_provider_creates_async_openai(self) -> None:
        """验证远程提供者使用 openai.AsyncOpenAI."""
        from app.models.embedding import EmbeddingModel

        provider = EmbeddingProviderConfig(
            provider=ProviderConfig(
                model="text-embedding-3-small",
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
            ),
        )
        emb = EmbeddingModel(provider=provider)
        with patch("app.models.embedding.openai.AsyncOpenAI") as mock_cls:
            mock_cls.return_value = MagicMock()
            _ = emb.client
        mock_cls.assert_called_once()

    async def test_encode_uses_client(self) -> None:
        """验证 encode 委托给缓存的客户端."""
        from app.models.embedding import EmbeddingModel

        provider = EmbeddingProviderConfig(
            provider=ProviderConfig(model="fake-model"), device="cpu"
        )
        emb = EmbeddingModel(provider=provider)
        mock_client = MagicMock()
        mock_client.encode.return_value = MagicMock(
            tolist=MagicMock(return_value=[0.1, 0.2, 0.3])
        )
        emb._client = mock_client
        result = await emb.encode("test")
        assert result == [0.1, 0.2, 0.3]


def test_judge_provider_config_from_dict() -> None:
    """测试 JudgeProviderConfig.from_dict 创建正确的配置."""
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


def test_judge_provider_config_defaults() -> None:
    """测试 JudgeProviderConfig 默认值被正确应用."""
    from app.models.settings import JudgeProviderConfig

    cfg = JudgeProviderConfig.from_dict({"model": "test"})
    assert cfg.provider.base_url is None
    assert cfg.provider.api_key is None
    assert cfg.temperature == 0.1


def test_llm_settings_loads_judge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """测试 LLMSettings 从配置加载 judge 提供者."""
    from app.models.settings import LLMSettings

    config = {
        "model_groups": {
            "default": {"models": ["local/qwen"]},
        },
        "model_providers": {
            "local": {"base_url": "http://localhost:8000", "api_key": "none"},
        },
        "judge": {"model": "deepseek-chat", "base_url": "https://api.deepseek.com/v1"},
    }
    config_file = tmp_path / "llm.toml"
    config_file.write_text(tomli_w.dumps(config))
    monkeypatch.setenv("CONFIG_PATH", str(config_file))

    settings = LLMSettings.load()
    assert settings.judge_provider is not None
    assert settings.judge_provider.provider.model == "deepseek-chat"
