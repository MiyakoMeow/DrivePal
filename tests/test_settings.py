"""模型设置加载器测试."""

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import tomli_w

from app.models.chat import ChatModel, clear_semaphore_cache
from app.models.embedding import EmbeddingModel
from app.models.settings import (
    EmbeddingProviderConfig,
    JudgeProviderConfig,
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


class TestDeepSeekThinkingMode:
    """DeepSeek thinking mode 参数转发测试."""

    @staticmethod
    def _make_provider(
        extra_params: dict[str, Any] | None = None,
    ) -> LLMProviderConfig:
        """创建含 extra_params 的 LLMProviderConfig."""
        return LLMProviderConfig(
            provider=ProviderConfig(
                model="deepseek-chat",
                base_url="https://api.deepseek.com/v1",
                api_key="sk-test",
            ),
            extra_params=extra_params or {},
        )

    def test_merge_api_kwargs_from_provider(self) -> None:
        """验证 reasoning_effort 从 provider extra_params 转发."""
        provider = self._make_provider({"reasoning_effort": "high"})
        result = ChatModel._merge_api_kwargs(provider, {})
        assert result["reasoning_effort"] == "high"

    def test_merge_api_kwargs_caller_overrides(self) -> None:
        """验证调用方 kwargs 优先级高于 provider extra_params."""
        provider = self._make_provider({"reasoning_effort": "low"})
        result = ChatModel._merge_api_kwargs(provider, {"reasoning_effort": "high"})
        assert result["reasoning_effort"] == "high"

    def test_merge_api_kwargs_auto_inject_thinking(self) -> None:
        """验证 reasoning_effort 已设置时自动注入 extra_body thinking=enabled."""
        provider = self._make_provider({"reasoning_effort": "high"})
        result = ChatModel._merge_api_kwargs(provider, {})
        assert result["reasoning_effort"] == "high"
        assert result["extra_body"] == {"thinking": {"type": "enabled"}}

    def test_merge_api_kwargs_preserves_existing_extra_body(self) -> None:
        """验证已有 extra_body 时不被 thinking 覆盖."""
        provider = self._make_provider(
            {"reasoning_effort": "high", "extra_body": {"custom": "value"}},
        )
        result = ChatModel._merge_api_kwargs(provider, {})
        assert result["extra_body"]["thinking"] == {"type": "enabled"}
        assert result["extra_body"]["custom"] == "value"

    def test_merge_api_kwargs_no_thinking_without_reasoning_effort(self) -> None:
        """验证无 reasoning_effort 时不注入 thinking."""
        provider = self._make_provider({})
        result = ChatModel._merge_api_kwargs(provider, {})
        assert "extra_body" not in result

    def test_merge_api_kwargs_extra_body_from_caller(self) -> None:
        """验证调用方可以传入自定义 extra_body."""
        provider = self._make_provider({})
        result = ChatModel._merge_api_kwargs(
            provider,
            {"extra_body": {"thinking": {"type": "disabled"}}},
        )
        assert result["extra_body"] == {"thinking": {"type": "disabled"}}

    def test_merge_api_kwargs_unknown_params_ignored(self) -> None:
        """验证 _EXTRA_API_PARAMS 之外的参数不转发."""
        provider = self._make_provider({"temperature": 0.1, "foo": "bar"})
        result = ChatModel._merge_api_kwargs(provider, {})
        assert "temperature" not in result
        assert "foo" not in result

    async def test_generate_forwards_reasoning_effort(self) -> None:
        """验证 generate() 将 reasoning_effort 传递给 API 调用."""
        providers = [
            LLMProviderConfig(
                provider=ProviderConfig(
                    model="deepseek-chat",
                    base_url="https://api.deepseek.com/v1",
                    api_key="sk-test",
                ),
                extra_params={"reasoning_effort": "high"},
            ),
        ]
        chat = ChatModel(providers=providers)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "reasoned answer"
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch(
            "app.models.chat._get_cached_client",
            AsyncMock(return_value=mock_client),
        ):
            result = await chat.generate("test query")

        assert result == "reasoned answer"
        mock_client.chat.completions.create.assert_called_once()
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["reasoning_effort"] == "high"
        assert call_kwargs["extra_body"] == {"thinking": {"type": "enabled"}}

    async def test_generate_accepts_caller_reasoning_effort(self) -> None:
        """验证调用方在 generate() 中传入 reasoning_effort 生效."""
        providers = [
            LLMProviderConfig(
                provider=ProviderConfig(
                    model="deepseek-chat",
                    base_url="https://api.deepseek.com/v1",
                    api_key="sk-test",
                ),
            ),
        ]
        chat = ChatModel(providers=providers)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "answer"
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch(
            "app.models.chat._get_cached_client",
            AsyncMock(return_value=mock_client),
        ):
            result = await chat.generate(
                "test",
                reasoning_effort="max",
            )

        assert result == "answer"
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["reasoning_effort"] == "max"
        assert call_kwargs["extra_body"] == {"thinking": {"type": "enabled"}}

    async def test_generate_without_thinking_normal(self) -> None:
        """验证无 thinking 参数时行为不变."""
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
        mock_response.choices[0].message.content = "normal answer"
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch(
            "app.models.chat._get_cached_client",
            AsyncMock(return_value=mock_client),
        ):
            result = await chat.generate("hello")

        assert result == "normal answer"
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert "reasoning_effort" not in call_kwargs
        assert "extra_body" not in call_kwargs

    def test_extra_params_from_model_string(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """验证模型字符串中的 extra params 经 _build_provider_config_from_ref 正确解析."""
        from app.models.settings import LLMSettings

        config = {
            "model_groups": {
                "default": {
                    "models": [
                        "deepseek/deepseek-chat?temperature=0.0&reasoning_effort=high",
                    ],
                },
            },
            "model_providers": {
                "deepseek": {
                    "base_url": "https://api.deepseek.com/v1",
                    "api_key_env": "DEEPSEEK_API_KEY",
                },
            },
        }
        config_file = tmp_path / "llm.toml"
        config_file.write_text(tomli_w.dumps(config))
        monkeypatch.setenv("CONFIG_PATH", str(config_file))
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        LLMSettings.load.cache_clear()

        providers = LLMSettings.load().get_model_group_providers("default")
        LLMSettings.load.cache_clear()

        assert len(providers) == 1
        assert providers[0].provider.model == "deepseek-chat"
        assert providers[0].temperature == 0.0
        assert providers[0].extra_params == {"reasoning_effort": "high"}


def test_judge_provider_config_from_dict() -> None:
    """测试 JudgeProviderConfig.from_dict 创建正确的配置."""
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
    assert cfg.temperature == TEMPERATURE_0_1


def test_judge_provider_config_defaults() -> None:
    """测试 JudgeProviderConfig 默认值被正确应用."""
    cfg = JudgeProviderConfig.from_dict({"model": "test"})
    assert cfg.provider.base_url is None
    assert cfg.provider.api_key is None
    assert cfg.temperature == TEMPERATURE_0_1


def test_llm_settings_loads_judge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """测试 LLMSettings 从配置加载 judge 提供者."""
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

    LLMSettings.load.cache_clear()
    settings = LLMSettings.load()
    LLMSettings.load.cache_clear()
    assert settings.judge_provider is not None
    assert settings.judge_provider.provider.model == "deepseek-chat"
