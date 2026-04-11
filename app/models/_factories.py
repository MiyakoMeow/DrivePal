"""模型工厂函数（延迟绑定，打破 settings ↔ chat/embedding 循环依赖）."""

from __future__ import annotations

from app.models.chat import ChatModel
from app.models.embedding import EmbeddingModel, get_cached_embedding_model
from app.models.settings import (
    LLMProviderConfig,
    LLMSettings,
    NoDefaultModelGroupError,
    NoJudgeModelConfiguredError,
    ProviderConfig,
)

_settings_cache: list[LLMSettings | None] = [None]


def _ensure_settings() -> LLMSettings:
    """确保设置已加载并返回."""
    if _settings_cache[0] is None:
        _settings_cache[0] = LLMSettings.load()
    return _settings_cache[0]


def get_chat_model(temperature: float | None = None) -> ChatModel:
    """从配置创建 ChatModel 实例（使用缓存避免重复加载）."""
    settings = _ensure_settings()
    if "default" not in settings.model_groups:
        raise NoDefaultModelGroupError
    providers = settings.get_model_group_providers("default")
    return ChatModel(providers=providers, temperature=temperature)


def get_embedding_model() -> EmbeddingModel:
    """从配置创建 EmbeddingModel 实例（使用缓存避免重复加载）."""
    return get_cached_embedding_model()


def get_judge_model() -> ChatModel:
    """从配置创建 judge ChatModel 实例（使用缓存避免重复加载）."""
    settings = _ensure_settings()
    if settings.judge_provider is None:
        raise NoJudgeModelConfiguredError
    provider = LLMProviderConfig(
        provider=ProviderConfig(
            model=settings.judge_provider.provider.model,
            base_url=settings.judge_provider.provider.base_url,
            api_key=settings.judge_provider.provider.api_key,
        ),
        temperature=settings.judge_provider.temperature,
    )
    return ChatModel(providers=[provider])
