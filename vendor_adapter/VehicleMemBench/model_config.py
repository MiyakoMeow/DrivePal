"""基准测试模型客户端配置."""

from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from openai import OpenAI

from app.models.model_string import get_model_group_providers

if TYPE_CHECKING:
    from app.models.chat import ChatModel
    from app.models.embedding import EmbeddingModel


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
    """从 model_groups.benchmark 配置中提取基准测试参数."""
    try:
        providers = get_model_group_providers("benchmark")
    except KeyError:
        raise ValueError(
            "model_groups.benchmark must be configured with at least one model reference"
        ) from None
    if not providers:
        raise ValueError(
            "model_groups.benchmark must be configured with at least one model reference"
        )
    provider = providers[0]
    return BenchmarkConfig(
        base_url=provider["base_url"],
        api_key=provider["api_key"],
        model=provider["model"],
        temperature=provider["temperature"],
        max_tokens=8192,
    )


@lru_cache(maxsize=1)
def get_benchmark_client() -> OpenAI:
    """获取配置好的基准测试 OpenAI 客户端."""
    cfg = get_benchmark_config()
    return OpenAI(base_url=cfg.base_url, api_key=cfg.api_key)


def get_store_chat_model() -> ChatModel:
    """获取用于记忆存储操作的聊天模型."""
    from app.models.settings import get_chat_model

    return get_chat_model()


def get_store_embedding_model() -> EmbeddingModel:
    """获取用于记忆存储操作的嵌入模型."""
    from app.models.settings import get_embedding_model

    return get_embedding_model()
