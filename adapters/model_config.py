"""基准测试模型客户端配置."""

import os

import tomllib
from functools import lru_cache
from pathlib import Path

from openai import OpenAI

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.embedding import EmbeddingModel
    from app.models.chat import ChatModel


def _get_config_path() -> Path:
    """获取配置文件路径，支持环境变量覆盖."""
    env_path = os.environ.get("CONFIG_PATH", "config/llm.toml")
    if Path(env_path).is_absolute():
        return Path(env_path)
    return Path(__file__).resolve().parent.parent / env_path


@lru_cache(maxsize=1)
def _load_config() -> dict:
    """从 TOML 文件加载配置（已缓存）."""
    config_path = _get_config_path()
    with config_path.open("rb") as f:
        return tomllib.load(f)


def get_benchmark_client() -> OpenAI:
    """获取配置好的基准测试 OpenAI 客户端."""
    config = _load_config()
    if "benchmark" in config:
        bc = config["benchmark"]
        api_key = os.environ.get(bc.get("api_key_env", ""), bc.get("api_key", ""))
        return OpenAI(
            base_url=bc["base_url"],
            api_key=api_key,
        )
    if not config.get("llm"):
        raise ValueError(
            "Configuration must contain at least one LLM provider in 'llm' array"
        )
    llm = config["llm"][0]
    return OpenAI(
        base_url=llm.get("base_url"),
        api_key=llm.get("api_key", ""),
    )


def get_benchmark_model_name() -> str:
    """从配置中获取基准测试模型名称."""
    config = _load_config()
    if "benchmark" in config:
        return config["benchmark"]["model"]
    return config["llm"][0]["model"]


def get_benchmark_temperature() -> float:
    """从配置中获取基准测试温度参数."""
    config = _load_config()
    if "benchmark" in config:
        return config["benchmark"].get("temperature", 0.0)
    return config["llm"][0].get("temperature", 0.7)


def get_benchmark_max_tokens() -> int:
    """从配置中获取基准测试最大 token 数."""
    config = _load_config()
    if "benchmark" in config:
        return config["benchmark"].get("max_tokens", 8192)
    return 8192


def get_store_chat_model() -> "ChatModel":
    """获取用于记忆存储操作的聊天模型."""
    from app.models.settings import get_chat_model

    return get_chat_model()


def get_store_embedding_model() -> "EmbeddingModel":
    """获取用于记忆存储操作的嵌入模型."""
    from app.models.settings import get_embedding_model

    return get_embedding_model()
