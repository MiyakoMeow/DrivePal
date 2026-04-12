"""统一 LLM/Embedding 配置加载器."""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.models.exceptions import ModelGroupNotFoundError, ProviderNotFoundError
from app.models.model_string import resolve_model_string
from app.models.types import ProviderConfig


class NoLLMConfigurationError(RuntimeError):
    """没有找到任何 LLM 配置时抛出."""

    def __init__(self) -> None:
        """初始化错误."""
        super().__init__("No LLM configuration found")


class MissingModelFieldError(ValueError):
    """缺少必需字段 'model' 时抛出."""

    def __init__(self) -> None:
        """初始化错误."""
        super().__init__("Missing required field 'model'")


class NoDefaultModelGroupError(RuntimeError):
    """没有默认模型组时抛出."""

    def __init__(self) -> None:
        """初始化错误."""
        super().__init__("No default model group configured")


class NoJudgeModelConfiguredError(RuntimeError):
    """没有配置 judge 模型时抛出."""

    def __init__(self) -> None:
        """初始化错误."""
        super().__init__("No judge model configured")


@dataclass
class LLMProviderConfig:
    """单个 LLM 服务提供商配置."""

    provider: ProviderConfig
    temperature: float = 0.7
    concurrency: int = 4

    @classmethod
    def from_dict(cls, d: dict) -> LLMProviderConfig:
        """从字典创建配置实例."""
        provider, extra = _build_provider_config_from_dict(
            d,
            {"temperature": 0.7, "concurrency": 4},
        )
        return cls(provider=provider, **extra)


@dataclass
class EmbeddingProviderConfig:
    """单个 Embedding 服务提供商配置."""

    provider: ProviderConfig

    @classmethod
    def from_dict(cls, d: dict) -> EmbeddingProviderConfig:
        """从字典创建配置实例."""
        provider, _ = _build_provider_config_from_dict(d, {})
        return cls(provider=provider)


@dataclass
class JudgeProviderConfig:
    """Judge 评估模型配置."""

    provider: ProviderConfig
    temperature: float = 0.1

    @classmethod
    def from_dict(cls, d: dict) -> JudgeProviderConfig:
        """从字典创建配置实例."""
        provider, extra = _build_provider_config_from_dict(d, {"temperature": 0.1})
        return cls(provider=provider, **extra)


@dataclass
class LLMSettings:
    """模型配置集合，包含 LLM 和 Embedding 提供商列表."""

    llm_providers: list[LLMProviderConfig] = field(default_factory=list)
    embedding_model: str | None = None
    judge_provider: JudgeProviderConfig | None = None
    model_groups: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    model_providers: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def load(cls) -> LLMSettings:
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
            raise NoLLMConfigurationError

        embedding_section = config_data.get("embedding")
        embedding_model = (
            embedding_section.get("model")
            if isinstance(embedding_section, dict)
            else None
        )

        judge_provider = _build_judge_provider(config_data)

        default_providers: list[LLMProviderConfig] = []
        if "default" in model_groups:
            default_providers.extend(
                _build_provider_config_from_ref(ref, model_providers)
                for ref in model_groups["default"].get("models", [])
            )

        return cls(
            llm_providers=default_providers,
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
            raise ModelGroupNotFoundError(name)

        model_refs = self.model_groups[name].get("models", [])
        if not model_refs:
            return []

        return [
            _build_provider_config_from_ref(ref, self.model_providers)
            for ref in model_refs
        ]

    def get_embedding_provider(self) -> EmbeddingProviderConfig | None:
        """解析 embedding_model 配置字符串，返回 EmbeddingProviderConfig."""
        if not self.embedding_model:
            return None
        resolved = resolve_model_string(self.embedding_model)
        if resolved.provider_name not in self.model_providers:
            raise ProviderNotFoundError(resolved.provider_name)
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
        )


def _build_provider_config_from_dict(
    d: dict,
    extra_fields: dict[str, Any],
) -> tuple[ProviderConfig, dict[str, Any]]:
    """从字典构建 ProviderConfig 和剩余字段.

    Args:
        d: 配置字典
        extra_fields: 需要提取的额外字段名到默认值的映射

    Returns:
        (ProviderConfig, 剩余字段字典) 元组

    Raises:
        ValueError: model 字段缺失时

    """
    model = d.get("model")
    if model is None:
        raise MissingModelFieldError
    provider = ProviderConfig(
        model=model,
        base_url=d.get("base_url"),
        api_key=d.get("api_key"),
    )
    result = {}
    for key, default in extra_fields.items():
        result[key] = d.get(key, default)
    return provider, result


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


def _build_provider_config_from_ref(
    ref: str,
    model_providers: dict[str, dict],
) -> LLMProviderConfig:
    """从模型引用字符串构建 LLMProviderConfig.

    Args:
        ref: 模型引用字符串，格式为 "provider/model_name"
        model_providers: 提供商配置字典

    Returns:
        LLMProviderConfig 实例

    Raises:
        ValueError: 提供商不存在或引用格式无效

    """
    resolved = resolve_model_string(ref)
    if resolved.provider_name not in model_providers:
        raise ProviderNotFoundError(resolved.provider_name)
    provider_config = model_providers[resolved.provider_name]
    api_key_env = provider_config.get("api_key_env")
    if api_key_env:
        api_key: str | None = os.environ.get(api_key_env, "")
    else:
        api_key = provider_config.get("api_key")
    concurrency = provider_config.get("concurrency", 4)
    return LLMProviderConfig(
        provider=ProviderConfig(
            model=resolved.model_name,
            base_url=provider_config.get("base_url"),
            api_key=api_key,
        ),
        temperature=resolved.params.get("temperature", 0.7),
        concurrency=concurrency,
    )


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
