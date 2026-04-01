"""统一 LLM/Embedding 配置加载器."""

from __future__ import annotations

import os

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.chat import ChatModel
    from app.models.embedding import EmbeddingModel


@dataclass
class ResolvedModel:
    """解析后的模型引用."""

    provider_name: str
    model_name: str
    params: dict[str, Any]


@dataclass
class ProviderConfig:
    """LLM 提供商基础配置."""

    model: str
    base_url: str | None = None
    api_key: str | None = None


@dataclass
class LLMProviderConfig:
    """单个 LLM 服务提供商配置."""

    provider: ProviderConfig
    temperature: float = 0.7

    @classmethod
    def from_dict(cls, d: dict) -> "LLMProviderConfig":
        """从字典创建配置实例."""
        return cls(
            provider=ProviderConfig(
                model=d["model"],
                base_url=d.get("base_url"),
                api_key=d.get("api_key"),
            ),
            temperature=d.get("temperature", 0.7),
        )


@dataclass
class EmbeddingProviderConfig:
    """单个 Embedding 服务提供商配置."""

    provider: ProviderConfig
    device: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "EmbeddingProviderConfig":
        """从字典创建配置实例."""
        return cls(
            provider=ProviderConfig(
                model=d["model"],
                base_url=d.get("base_url"),
                api_key=d.get("api_key"),
            ),
            device=d.get("device"),
        )


@dataclass
class JudgeProviderConfig:
    """Judge 评估模型配置."""

    provider: ProviderConfig
    temperature: float = 0.1

    @classmethod
    def from_dict(cls, d: dict) -> "JudgeProviderConfig":
        """从字典创建配置实例."""
        return cls(
            provider=ProviderConfig(
                model=d["model"],
                base_url=d.get("base_url"),
                api_key=d.get("api_key"),
            ),
            temperature=d.get("temperature", 0.1),
        )


@dataclass
class LLMSettings:
    """模型配置集合，包含 LLM 和 Embedding 提供商列表."""

    llm_providers: list[LLMProviderConfig] = field(default_factory=list)
    embedding_model: str | None = None
    judge_provider: JudgeProviderConfig | None = None
    model_groups: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    model_providers: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def load(cls) -> "LLMSettings":
        """按优先级链加载配置，找不到任何 LLM 配置则抛 RuntimeError."""
        config_data: dict = {}
        config_path_env = os.environ.get("CONFIG_PATH", "config/llm.toml")
        if Path(config_path_env).is_absolute():
            config_path = Path(config_path_env)
        else:
            config_path = Path(__file__).resolve().parents[2] / config_path_env
        if config_path.is_file():
            with config_path.open("rb") as f:
                config_data = tomllib.load(f)

        model_groups = dict(config_data.get("model_groups", {}))
        model_providers = dict(config_data.get("model_providers", {}))

        if not model_groups:
            raise RuntimeError(
                "No LLM configuration found. Add [model_groups.default] to config/llm.toml"
            )

        embedding_section = config_data.get("embedding")
        embedding_model = (
            embedding_section.get("model")
            if isinstance(embedding_section, dict)
            else None
        )

        judge_provider = _build_judge_provider(config_data)

        return cls(
            llm_providers=[],
            embedding_model=embedding_model,
            judge_provider=judge_provider,
            model_groups=model_groups,
            model_providers=model_providers,
        )

    def get_model_group_providers(self, name: str) -> list[LLMProviderConfig]:
        """按组名获取 LLMProviderConfig 列表.

        Args:
            name: 模型组名称

        Returns:
            LLMProviderConfig 列表

        Raises:
            KeyError: 模型组不存在时

        """
        if name not in self.model_groups:
            raise KeyError(f"Model group '{name}' not found")

        from adapters.model_config import resolve_model_string

        model_refs = self.model_groups[name].get("models", [])
        if not model_refs:
            return []

        result = []
        for ref in model_refs:
            resolved = resolve_model_string(ref)
            if resolved.provider_name not in self.model_providers:
                raise ValueError(
                    f"Provider '{resolved.provider_name}' not found in model_providers"
                )
            provider_config = self.model_providers[resolved.provider_name]
            api_key_env = provider_config.get("api_key_env")
            if api_key_env:
                api_key: str | None = os.environ.get(api_key_env, "")
            else:
                api_key = provider_config.get("api_key")
            result.append(
                LLMProviderConfig(
                    provider=ProviderConfig(
                        model=resolved.model_name,
                        base_url=provider_config.get("base_url"),
                        api_key=api_key,
                    ),
                    temperature=resolved.params.get("temperature", 0.7),
                )
            )
        return result

    def get_embedding_provider(self) -> EmbeddingProviderConfig | None:
        """解析 embedding_model 配置字符串，返回 EmbeddingProviderConfig."""
        if not self.embedding_model:
            return None
        from adapters.model_config import resolve_model_string

        resolved = resolve_model_string(self.embedding_model)
        if resolved.provider_name not in self.model_providers:
            raise ValueError(
                f"Provider '{resolved.provider_name}' not found in model_providers"
            )
        provider_config = self.model_providers[resolved.provider_name]
        api_key_env = provider_config.get("api_key_env")
        if api_key_env:
            api_key: str | None = os.environ.get(api_key_env, "")
        else:
            api_key = provider_config.get("api_key")
        return EmbeddingProviderConfig(
            provider=ProviderConfig(
                model=resolved.model_name,
                base_url=provider_config.get("base_url"),
                api_key=api_key,
            ),
            device=resolved.params.get("device"),
        )


def _build_env_provider(prefix: str) -> LLMProviderConfig | None:
    """从环境变量构建 provider 配置."""
    model = os.getenv(f"{prefix}_MODEL")
    if not model:
        return None
    return LLMProviderConfig(
        provider=ProviderConfig(
            model=model,
            base_url=os.getenv(f"{prefix}_BASE_URL"),
            api_key=os.getenv(f"{prefix}_API_KEY"),
        ),
    )


def get_chat_model(temperature: float | None = None) -> "ChatModel":
    """从配置创建 ChatModel 实例."""
    from app.models.chat import ChatModel

    settings = LLMSettings.load()
    if "default" not in settings.model_groups:
        raise RuntimeError("No default model group configured")
    providers = settings.get_model_group_providers("default")
    return ChatModel(providers=providers, temperature=temperature)


def get_embedding_model() -> "EmbeddingModel":
    """从配置创建 EmbeddingModel 实例（使用缓存避免重复加载）."""
    from app.models.embedding import get_cached_embedding_model

    return get_cached_embedding_model()


def _build_judge_provider(config_data: dict) -> JudgeProviderConfig | None:
    """从配置文件或环境变量构建 judge provider."""
    judge_model = os.getenv("JUDGE_MODEL")
    judge_dict = config_data.get("judge")
    if judge_model:
        return JudgeProviderConfig(
            provider=ProviderConfig(
                model=judge_model,
                base_url=os.getenv("JUDGE_BASE_URL"),
                api_key=os.getenv("JUDGE_API_KEY"),
            ),
            temperature=float(os.getenv("JUDGE_TEMPERATURE", "0.1")),
        )
    if judge_dict:
        return JudgeProviderConfig.from_dict(judge_dict)
    return None


def get_judge_model() -> "ChatModel":
    """从配置创建 judge ChatModel 实例."""
    from app.models.chat import ChatModel

    settings = LLMSettings.load()
    if settings.judge_provider is None:
        raise RuntimeError(
            "No judge model configured. Set JUDGE_MODEL or add 'judge' to config/llm.toml"
        )
    provider = LLMProviderConfig(
        provider=ProviderConfig(
            model=settings.judge_provider.provider.model,
            base_url=settings.judge_provider.provider.base_url,
            api_key=settings.judge_provider.provider.api_key,
        ),
        temperature=settings.judge_provider.temperature,
    )
    return ChatModel(providers=[provider])
