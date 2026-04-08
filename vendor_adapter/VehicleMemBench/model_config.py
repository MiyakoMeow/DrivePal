"""基准测试模型客户端配置."""

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from openai import OpenAI

if TYPE_CHECKING:
    from app.models.embedding import EmbeddingModel
    from app.models.chat import ChatModel

from app.models.model_string import _load_config, _normalize_llm_config


@dataclass(frozen=True)
class BenchmarkConfig:
    """基准测试配置（一次性提取所有字段）."""

    base_url: str
    api_key: str
    model: str
    temperature: float
    max_tokens: int


@lru_cache(maxsize=1)
def get_benchmark_config() -> BenchmarkConfig:
    """从配置中一次性提取所有基准测试参数."""
    config = _load_config()
    if "benchmark" in config:
        bc = config["benchmark"]
        api_key_env = bc.get("api_key_env", "")
        if api_key_env:
            api_key = os.environ.get(api_key_env, bc.get("api_key", ""))
        else:
            api_key = bc.get("api_key", "")
        return BenchmarkConfig(
            base_url=bc["base_url"],
            api_key=api_key,
            model=bc["model"],
            temperature=bc.get("temperature", 0.0),
            max_tokens=bc.get("max_tokens", 8192),
        )
    llm_providers = _normalize_llm_config(config)
    if not llm_providers:
        raise ValueError(
            "Configuration must contain at least one LLM provider in 'llm' array"
        )
    llm = llm_providers[0]
    return BenchmarkConfig(
        base_url=llm.get("base_url", ""),
        api_key=llm.get("api_key", ""),
        model=llm["model"],
        temperature=llm.get("temperature", 0.0),
        max_tokens=8192,
    )


@lru_cache(maxsize=1)
def get_benchmark_client() -> OpenAI:
    """获取配置好的基准测试 OpenAI 客户端."""
    cfg = get_benchmark_config()
    return OpenAI(base_url=cfg.base_url, api_key=cfg.api_key)


def get_store_chat_model() -> "ChatModel":
    """获取用于记忆存储操作的聊天模型."""
    from app.models.settings import get_chat_model

    return get_chat_model()


def get_store_embedding_model() -> "EmbeddingModel":
    """获取用于记忆存储操作的嵌入模型."""
    from app.models.settings import get_embedding_model

    return get_embedding_model()
