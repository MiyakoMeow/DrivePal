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
    model: str
    base_url: str | None = None
    api_key: str | None = None
    temperature: float = 0.7

    @classmethod
    def from_dict(cls, d: dict) -> "LLMProviderConfig":
        return cls(
            model=d["model"],
            base_url=d.get("base_url"),
            api_key=d.get("api_key"),
            temperature=d.get("temperature", 0.7),
        )


@dataclass
class EmbeddingProviderConfig:
    model: str
    device: str = "cpu"
    base_url: str | None = None
    api_key: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "EmbeddingProviderConfig":
        return cls(
            model=d["model"],
            device=d.get("device", "cpu"),
            base_url=d.get("base_url"),
            api_key=d.get("api_key"),
        )


@dataclass
class LLMSettings:
    llm_providers: list[LLMProviderConfig] = field(default_factory=list)
    embedding_providers: list[EmbeddingProviderConfig] = field(default_factory=list)

    @classmethod
    def load(cls) -> "LLMSettings":
        config_data: dict = {}
        config_path = os.path.join(os.getcwd(), CONFIG_PATH)
        if os.path.isfile(config_path):
            with open(config_path) as f:
                config_data = json.load(f)

        llm_providers: list[LLMProviderConfig] = []
        for item in config_data.get("llm", []):
            llm_providers.append(LLMProviderConfig.from_dict(item))

        openai_env = _build_openai_env_provider()
        if openai_env is not None:
            llm_providers.append(openai_env)

        deepseek_env = _build_deepseek_env_provider()
        if deepseek_env is not None:
            llm_providers.append(deepseek_env)

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

        return cls(llm_providers=deduped, embedding_providers=embedding_providers)


def _build_openai_env_provider() -> LLMProviderConfig | None:
    model = os.getenv("OPENAI_MODEL")
    if not model:
        return None
    return LLMProviderConfig(
        model=model,
        base_url=os.getenv("OPENAI_BASE_URL"),
        api_key=os.getenv("OPENAI_API_KEY"),
    )


def _build_deepseek_env_provider() -> LLMProviderConfig | None:
    model = os.getenv("DEEPSEEK_MODEL")
    if not model:
        return None
    return LLMProviderConfig(
        model=model,
        base_url=os.getenv("DEEPSEEK_BASE_URL"),
        api_key=os.getenv("DEEPSEEK_API_KEY"),
    )


def get_chat_model(temperature: float | None = None) -> "ChatModel":
    from app.models.chat import ChatModel

    settings = LLMSettings.load()
    return ChatModel(providers=settings.llm_providers, temperature=temperature)


def get_embedding_model(device: str | None = None) -> "EmbeddingModel":
    from app.models.embedding import EmbeddingModel

    settings = LLMSettings.load()
    return EmbeddingModel(providers=settings.embedding_providers, device=device)
