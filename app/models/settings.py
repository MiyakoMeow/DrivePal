"""统一 LLM/Embedding 配置加载器."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.chat import ChatModel
    from app.models.embedding import EmbeddingModel


CONFIG_PATH = "config/llm.json"


@dataclass
class LLMProviderConfig:
    """单个 LLM 服务提供商配置."""

    model: str
    base_url: str | None = None
    api_key: str | None = None
    temperature: float = 0.7

    @classmethod
    def from_dict(cls, d: dict) -> "LLMProviderConfig":
        """从字典创建配置实例."""
        return cls(
            model=d["model"],
            base_url=d.get("base_url"),
            api_key=d.get("api_key"),
            temperature=d.get("temperature", 0.7),
        )


@dataclass
class EmbeddingProviderConfig:
    """单个 Embedding 服务提供商配置."""

    model: str
    device: str = "cpu"
    base_url: str | None = None
    api_key: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "EmbeddingProviderConfig":
        """从字典创建配置实例."""
        return cls(
            model=d["model"],
            device=d.get("device", "cpu"),
            base_url=d.get("base_url"),
            api_key=d.get("api_key"),
        )


@dataclass
class JudgeProviderConfig:
    """Judge 评估模型配置."""

    model: str
    base_url: str | None = None
    api_key: str | None = None
    temperature: float = 0.1

    @classmethod
    def from_dict(cls, d: dict) -> "JudgeProviderConfig":
        """从字典创建配置实例."""
        return cls(
            model=d["model"],
            base_url=d.get("base_url"),
            api_key=d.get("api_key"),
            temperature=d.get("temperature", 0.1),
        )


@dataclass
class LLMSettings:
    """模型配置集合，包含 LLM 和 Embedding 提供商列表."""

    llm_providers: list[LLMProviderConfig] = field(default_factory=list)
    embedding_providers: list[EmbeddingProviderConfig] = field(default_factory=list)
    judge_provider: JudgeProviderConfig | None = None

    @classmethod
    def load(cls) -> "LLMSettings":
        """按优先级链加载配置，找不到任何 LLM 配置则抛 RuntimeError."""
        config_data: dict = {}
        config_path = os.path.join(os.getcwd(), CONFIG_PATH)
        if os.path.isfile(config_path):
            with open(config_path) as f:
                config_data = json.load(f)

        llm_providers: list[LLMProviderConfig] = []
        for item in config_data.get("llm", []):
            llm_providers.append(LLMProviderConfig.from_dict(item))

        for prefix in ("OPENAI", "DEEPSEEK"):
            env_provider = _build_env_provider(prefix)
            if env_provider is not None:
                llm_providers.append(env_provider)

        if not llm_providers:
            raise RuntimeError(
                "No LLM configuration found. Set OPENAI_MODEL/DEEPSEEK_MODEL or create config/llm.json"
            )

        seen = set()
        deduped = []
        for p in llm_providers:
            key = (p.model, p.base_url)
            if key not in seen:
                seen.add(key)
                deduped.append(p)

        embedding_providers = [
            EmbeddingProviderConfig.from_dict(item)
            for item in config_data.get("embedding", [])
        ]

        judge_provider = _build_judge_provider(config_data)

        return cls(
            llm_providers=deduped,
            embedding_providers=embedding_providers,
            judge_provider=judge_provider,
        )


def _build_env_provider(prefix: str) -> LLMProviderConfig | None:
    """从环境变量构建 provider 配置."""
    model = os.getenv(f"{prefix}_MODEL")
    if not model:
        return None
    return LLMProviderConfig(
        model=model,
        base_url=os.getenv(f"{prefix}_BASE_URL"),
        api_key=os.getenv(f"{prefix}_API_KEY"),
    )


def get_chat_model(temperature: float | None = None) -> "ChatModel":
    """从配置创建 ChatModel 实例."""
    from app.models.chat import ChatModel

    settings = LLMSettings.load()
    return ChatModel(providers=settings.llm_providers, temperature=temperature)


def get_embedding_model(device: str | None = None) -> "EmbeddingModel":
    """从配置创建 EmbeddingModel 实例（使用缓存避免重复加载）."""
    from app.models.embedding import get_cached_embedding_model

    return get_cached_embedding_model(device=device)


def _build_judge_provider(config_data: dict) -> JudgeProviderConfig | None:
    """从配置文件或环境变量构建 judge provider."""
    judge_model = os.getenv("JUDGE_MODEL")
    judge_dict = config_data.get("judge")
    if judge_model:
        return JudgeProviderConfig(
            model=judge_model,
            base_url=os.getenv("JUDGE_BASE_URL"),
            api_key=os.getenv("JUDGE_API_KEY"),
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
            "No judge model configured. Set JUDGE_MODEL or add 'judge' to config/llm.json"
        )
    provider = LLMProviderConfig(
        model=settings.judge_provider.model,
        base_url=settings.judge_provider.base_url,
        api_key=settings.judge_provider.api_key,
        temperature=settings.judge_provider.temperature,
    )
    return ChatModel(providers=[provider])
