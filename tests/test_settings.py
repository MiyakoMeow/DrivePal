"""模型设置加载器测试."""

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import tomli_w

from app.models.chat import ChatModel, clear_semaphore_cache
from app.models.embedding import EmbeddingModel
from app.models.settings import (
    EmbeddingProviderConfig,
    LLMProviderConfig,
    LLMSettings,
)
from app.models.types import ProviderConfig
from tests._helpers import _mock_async_client

if TYPE_CHECKING:
    from pathlib import Path

# 测试用魔法值常量
DEFAULT_TEMPERATURE = 0.7
TEMPERATURE_0_5 = 0.5
TEMPERATURE_0_1 = 0.1
DEFAULT_CONCURRENCY = 4
CONCURRENCY_8 = 8
CONCURRENCY_16 = 16
CALL_COUNT_2 = 2


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
                "concurrency": 8,
            },
        )
        assert cfg.provider.model == "gpt-4"
        assert cfg.provider.base_url == "https://api.openai.com/v1"
        assert cfg.provider.api_key == "sk-test"
        assert cfg.temperature == TEMPERATURE_0_5
        assert cfg.concurrency == CONCURRENCY_8

    def test_from_dict_defaults(self) -> None:
        """验证可选字段缺失时的默认值."""
        cfg = LLMProviderConfig.from_dict({"model": "test"})
        assert cfg.provider.model == "test"
        assert cfg.provider.base_url is None
        assert cfg.provider.api_key is None
        assert cfg.temperature == DEFAULT_TEMPERATURE
        assert cfg.concurrency == DEFAULT_CONCURRENCY


class TestEmbeddingProviderConfig:
    """EmbeddingProviderConfig 测试."""

    def test_from_dict_remote(self) -> None:
        """验证远程 OpenAI 兼容提供者解析."""
        cfg = EmbeddingProviderConfig.from_dict(
            {
                "model": "text-embedding-3-small",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test",
            },
        )
        assert cfg.provider.model == "text-embedding-3-small"
        assert cfg.provider.base_url == "https://api.openai.com/v1"


class TestLLMSettingsLoad:
    """LLMSettings.load 配置加载测试."""

    def test_load_from_config_file(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
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
                    },
                    "embedding": {"model": "openai/text-embedding-3-small"},
                },
            ),
        )
        monkeypatch.setenv("CONFIG_PATH", str(config_file))
        LLMSettings.load.cache_clear()
        settings = LLMSettings.load()
        LLMSettings.load.cache_clear()
        assert "default" in settings.model_groups
        assert settings.embedding_model == "openai/text-embedding-3-small"

    def test_load_no_config_raises(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """验证无 LLM 配置时抛出 RuntimeError."""
        LLMSettings.load.cache_clear()
        monkeypatch.setenv("CONFIG_PATH", str(tmp_path / "nonexistent.toml"))
        with pytest.raises(RuntimeError, match="No LLM configuration found"):
            LLMSettings.load()

    def test_get_embedding_provider_remote(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
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
        LLMSettings.load.cache_clear()
        settings = LLMSettings.load()
        provider = settings.get_embedding_provider()
        assert provider is not None
        assert provider.provider.model == "text-embedding-3-small"
        assert provider.provider.base_url == "https://api.openai.com/v1"
        LLMSettings.load.cache_clear()

    def test_get_embedding_provider_none_when_not_configured(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
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
        LLMSettings.load.cache_clear()
        settings = LLMSettings.load()
        assert settings.get_embedding_provider() is None
        LLMSettings.load.cache_clear()

    def test_load_with_model_groups(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
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
                },
            ),
        )
        monkeypatch.setenv("CONFIG_PATH", str(config_file))
        LLMSettings.load.cache_clear()
        settings = LLMSettings.load()
        assert "default" in settings.model_groups
        providers = settings.get_model_group_providers("default")
        assert len(providers) == 1
        assert providers[0].provider.model == "gpt-4"
        LLMSettings.load.cache_clear()

    def test_get_model_group_providers_includes_concurrency(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """验证 get_model_group_providers 返回的配置包含 concurrency."""
        config = {
            "model_groups": {
                "default": {"models": ["openai/gpt-4"]},
            },
            "model_providers": {
                "openai": {
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "sk-a",
                    "concurrency": 16,
                },
            },
        }
        config_file = tmp_path / "config" / "llm.toml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(tomli_w.dumps(config))
        monkeypatch.setenv("CONFIG_PATH", str(config_file))
        LLMSettings.load.cache_clear()
        settings = LLMSettings.load()
        providers = settings.get_model_group_providers("default")
        assert providers[0].concurrency == CONCURRENCY_16
        LLMSettings.load.cache_clear()


class TestChatModelFallback:
    """ChatModel 多提供者回退行为测试."""

    @pytest.fixture(autouse=True)
    def _clean_cache(self):
        """每个测试前后清理客户端缓存."""
        clear_semaphore_cache()
        yield
        clear_semaphore_cache()

    async def test_generate_with_single_provider(self) -> None:
        """验证单个提供者成功生成."""
        providers = [
            LLMProviderConfig(
                provider=ProviderConfig(
                    model="test-model",
                    base_url="http://fake:8000/v1",
                    api_key="sk-test",
                ),
            ),
        ]
        chat = ChatModel(providers=providers)
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "response"
        mock_client = _mock_async_client()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        with patch(
            "app.models.chat._get_cached_client", AsyncMock(return_value=mock_client)
        ):
            result = await chat.generate("hello")
        assert result == "response"

    async def test_generate_falls_back_on_error(self) -> None:
        """验证第一个失败时回退到下一个提供者."""
        providers = [
            LLMProviderConfig(
                provider=ProviderConfig(
                    model="bad-model",
                    base_url="http://fake1:8000/v1",
                    api_key="sk-bad",
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

        def mock_create(_provider: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                client = _mock_async_client()
                client.chat.completions.create = AsyncMock(
                    side_effect=RuntimeError("API error"),
                )
                return client
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "fallback response"
            client = _mock_async_client()
            client.chat.completions.create = AsyncMock(return_value=mock_response)
            return client

        with patch("app.models.chat._get_cached_client", side_effect=mock_create):
            result = await chat.generate("hello")
        assert result == "fallback response"
        assert call_count == CALL_COUNT_2

    async def test_generate_all_providers_fail_raises(self) -> None:
        """验证所有提供者失败时抛出 RuntimeError."""
        providers = [
            LLMProviderConfig(
                provider=ProviderConfig(
                    model="bad1",
                    base_url="http://fake1:8000/v1",
                    api_key="sk-1",
                ),
            ),
            LLMProviderConfig(
                provider=ProviderConfig(
                    model="bad2",
                    base_url="http://fake2:8000/v1",
                    api_key="sk-2",
                ),
            ),
        ]
        chat = ChatModel(providers=providers)
        mock_client = _mock_async_client()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("fail"),
        )

        with (
            patch(
                "app.models.chat._get_cached_client",
                AsyncMock(return_value=mock_client),
            ),
            pytest.raises(RuntimeError, match="All LLM providers failed"),
        ):
            await chat.generate("hello")


class TestEmbeddingModelFallback:
    """EmbeddingModel 单提供者测试."""

    async def test_encode_uses_client(self) -> None:
        """验证 encode 委托给 openai 客户端."""
        provider = EmbeddingProviderConfig(
            provider=ProviderConfig(
                model="text-embedding-3-small",
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
            ),
        )
        emb = EmbeddingModel(provider=provider)
        mock_resp = MagicMock()
        mock_resp.data = [MagicMock()]
        mock_resp.data[0].embedding = [0.1, 0.2, 0.3]
        mock_client = MagicMock()
        mock_client.embeddings = MagicMock()
        mock_client.embeddings.create = AsyncMock(return_value=mock_resp)
        emb._client = mock_client
        result = await emb.encode("test")
        assert result == [0.1, 0.2, 0.3]


def test_validate_settings_invalid_alpha():
    """校验 retrieval_alpha=0 触发警告。"""
    from app.memory.memory_bank.config import MemoryBankConfig, validate_settings

    cfg = MemoryBankConfig.model_construct(retrieval_alpha=0.0)
    warns = validate_settings(cfg)
    assert len(warns) > 0
    assert "retrieval_alpha" in warns[0]


def test_validate_settings_ok():
    """校验默认配置不触发警告。"""
    from app.memory.memory_bank.config import MemoryBankConfig, validate_settings

    cfg = MemoryBankConfig()
    warns = validate_settings(cfg)
    assert len(warns) == 0


def test_llm_settings_judge_model_group_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """测试 judge_model_group 默认值."""
    config = {
        "model_groups": {
            "default": {"models": ["local/qwen"]},
        },
        "model_providers": {
            "local": {"base_url": "http://localhost:8000", "api_key": "none"},
        },
    }
    config_file = tmp_path / "llm.toml"
    config_file.write_text(tomli_w.dumps(config))
    monkeypatch.setenv("CONFIG_PATH", str(config_file))

    LLMSettings.load.cache_clear()
    settings = LLMSettings.load()
    LLMSettings.load.cache_clear()
    assert settings.judge_model_group == "judge"


def test_llm_settings_loads_judge_model_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """测试 LLMSettings 从配置加载 judge 模型组."""
    config = {
        "model_groups": {
            "default": {"models": ["local/qwen"]},
            "judge": {"models": ["local/qwen"]},
        },
        "model_providers": {
            "local": {"base_url": "http://localhost:8000", "api_key": "none"},
        },
    }
    config_file = tmp_path / "llm.toml"
    config_file.write_text(tomli_w.dumps(config))
    monkeypatch.setenv("CONFIG_PATH", str(config_file))

    LLMSettings.load.cache_clear()
    settings = LLMSettings.load()
    LLMSettings.load.cache_clear()
    assert settings.judge_model_group == "judge"
    providers = settings.get_model_group_providers("judge")
    assert len(providers) == 1
    assert providers[0].provider.model == "qwen"


def test_llm_settings_judge_model_group_custom_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """测试自定义 judge_model_group 名称."""
    config = {
        "model_groups": {
            "default": {"models": ["local/qwen"]},
            "eval": {"models": ["local/qwen"]},
        },
        "model_providers": {
            "local": {"base_url": "http://localhost:8000", "api_key": "none"},
        },
        "judge_model_group": "eval",
    }
    config_file = tmp_path / "llm.toml"
    config_file.write_text(tomli_w.dumps(config))
    monkeypatch.setenv("CONFIG_PATH", str(config_file))

    LLMSettings.load.cache_clear()
    settings = LLMSettings.load()
    LLMSettings.load.cache_clear()
    assert settings.judge_model_group == "eval"
