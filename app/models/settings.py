"""统一 LLM/Embedding 配置加载器."""

import os
import tomllib
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from app.config import ensure_config, get_config_root
from app.exceptions import AppError
from app.models.exceptions import ModelGroupNotFoundError, ProviderNotFoundError
from app.models.model_string import resolve_model_string
from app.models.types import ProviderConfig

_LLM_TOML_DEFAULTS: dict = {
    "model_groups": {
        "default": {"models": ["deepseek/deepseek-v4-flash?temperature=0.0"]},
        "smart": {"models": ["deepseek/deepseek-v4-flash?temperature=0.0"]},
        "fast": {"models": ["deepseek/deepseek-v4-flash?temperature=0.0"]},
        "balanced": {"models": ["deepseek/deepseek-v4-flash?temperature=0.0"]},
        "judge": {"models": ["deepseek/deepseek-v4-pro?temperature=0.1"]},
    },
    "model_providers": {
        "deepseek": {
            "base_url": "https://api.deepseek.com/v1",
            "api_key_env": "DEEPSEEK_API_KEY",
            "concurrency": 8,
        },
        "zhipu-coding": {
            "base_url": "https://open.bigmodel.cn/api/coding/paas/v4",
            "api_key_env": "ZHIPU_API_KEY",
            "concurrency": 3,
        },
        "openrouter": {
            "base_url": "https://openrouter.ai/api/v1",
            "api_key_env": "OPENROUTER_API_KEY",
            "concurrency": 16,
        },
    },
    "embedding": {"model": "openrouter/baai/bge-m3"},
}


class NoLLMConfigurationError(AppError):
    """没有找到任何 LLM 配置时抛出."""

    def __init__(self) -> None:
        super().__init__(code="MODEL_NO_CONFIG", message="No LLM configuration found")


class MissingModelFieldError(AppError):
    """缺少必需字段 'model' 时抛出."""

    def __init__(self) -> None:
        super().__init__(
            code="MODEL_MISSING_FIELD", message="Missing required field 'model'"
        )


class NoDefaultModelGroupError(AppError):
    """没有默认模型组时抛出."""

    def __init__(self) -> None:
        super().__init__(
            code="MODEL_NO_DEFAULT_GROUP", message="No default model group configured"
        )


class NoJudgeModelConfiguredError(AppError):
    """没有配置 judge 模型时抛出."""

    def __init__(self) -> None:
        super().__init__(code="MODEL_NO_JUDGE", message="No judge model configured")


@dataclass
class LLMProviderConfig:
    """单个 LLM 服务提供商配置."""

    provider: ProviderConfig
    temperature: float = 0.7
    concurrency: int = 4

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LLMProviderConfig:
        """从字典创建配置实例."""
        return _make_provider_config(cls, d, {"temperature": 0.7, "concurrency": 4})


@dataclass
class EmbeddingProviderConfig:
    """单个 Embedding 服务提供商配置."""

    provider: ProviderConfig

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> EmbeddingProviderConfig:
        """从字典创建配置实例."""
        return _make_provider_config(cls, d, {})


@dataclass
class LLMSettings:
    """模型配置集合，包含 LLM 和 Embedding 提供商列表."""

    llm_providers: list[LLMProviderConfig] = field(default_factory=list)
    embedding_model: str | None = None
    judge_model_group: str = "judge"
    model_groups: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    model_providers: dict[str, dict] = field(default_factory=dict)

    @classmethod
    @cache
    def load(cls) -> LLMSettings:
        """按优先级链加载配置，缺失则自动生成默认配置。"""
        config_path_env = os.environ.get("CONFIG_PATH")
        if config_path_env:
            # 用户显式指定路径：使用指定路径，不自动生成
            config_path = Path(config_path_env)
            if not config_path.is_absolute():
                config_path = Path(__file__).resolve().parents[2] / config_path_env
            if config_path.is_file():
                with config_path.open("rb") as f:
                    config_data = tomllib.load(f)
            else:
                config_data = {}
        else:
            config_path = get_config_root() / "llm.toml"
            config_data = ensure_config(config_path, _LLM_TOML_DEFAULTS)

        raw_groups = config_data.get("model_groups")
        model_groups = dict(raw_groups) if isinstance(raw_groups, dict) else {}
        raw_providers = config_data.get("model_providers")
        model_providers = dict(raw_providers) if isinstance(raw_providers, dict) else {}

        if not model_groups:
            raise NoLLMConfigurationError

        embedding_section = config_data.get("embedding")
        embedding_model = (
            embedding_section.get("model")
            if isinstance(embedding_section, dict)
            else None
        )

        judge_model_group = str(config_data.get("judge_model_group", "judge"))

        default_providers: list[LLMProviderConfig] = []
        if "default" in model_groups:
            default_providers.extend(
                _build_provider_config_from_ref(ref, model_providers)
                for ref in model_groups["default"].get("models", [])
            )

        return cls(
            llm_providers=default_providers,
            embedding_model=embedding_model,
            judge_model_group=judge_model_group,
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
        api_key = _resolve_api_key(provider_config)
        return EmbeddingProviderConfig(
            provider=ProviderConfig(
                model=resolved.model_name,
                base_url=provider_config.get("base_url"),
                api_key=api_key,
            ),
        )


def _resolve_api_key(provider_config: dict) -> str | None:
    """从 provider 配置中解析 api_key。

    优先读取 api_key_env 指向的环境变量；环境变量缺失或为空时抛 ValueError。
    无 api_key_env 时回退到直接读取 api_key 字段（可为 None）。

    Raises:
        ValueError: api_key_env 指定了但对应环境变量不存在或为空。

    """
    key_env = provider_config.get("api_key_env")
    if key_env:
        key = os.environ.get(key_env)
        if not key:
            msg = f"Environment variable '{key_env}' is not set or empty"
            raise ValueError(msg)
        return key
    return provider_config.get("api_key")


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
    api_key = _resolve_api_key(d)
    provider = ProviderConfig(
        model=model,
        base_url=d.get("base_url"),
        api_key=api_key,
    )
    result = {}
    for key, default in extra_fields.items():
        result[key] = d.get(key, default)
    return provider, result


def _make_provider_config[T](
    cls: type[T],
    d: dict[str, Any],
    defaults: dict[str, Any],
) -> T:
    """泛型工厂：从字典构建 ProviderConfig 子类实例。

    Args:
        cls: ProviderConfig 子类。
        d: 配置字典。
        defaults: 额外字段名到默认值的映射。

    Returns:
        构造的 ProviderConfig 实例。

    """
    provider, extra = _build_provider_config_from_dict(d, defaults)
    return cls(provider=provider, **extra)


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
    api_key = _resolve_api_key(provider_config)
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
