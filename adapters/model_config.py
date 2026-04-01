"""基准测试模型客户端配置."""

import os

import tomllib
from functools import lru_cache
from pathlib import Path

from openai import OpenAI

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.embedding import EmbeddingModel
    from app.models.chat import ChatModel

from app.models.settings import ResolvedModel


def _get_config_path() -> Path:
    """获取配置文件路径，支持环境变量覆盖."""
    env_path = os.environ.get("CONFIG_PATH", "config/llm.toml")
    if Path(env_path).is_absolute():
        return Path(env_path)
    return Path(__file__).resolve().parent.parent / env_path


def _normalize_llm_config(config: dict) -> list[dict]:
    """规范化 LLM 配置，支持 dict 或 list 格式."""
    llm_data = config.get("llm", [])
    if isinstance(llm_data, dict):
        return [llm_data]
    if isinstance(llm_data, list):
        if not all(isinstance(item, dict) for item in llm_data):
            msg = "Each item in 'llm' must be a table/object"
            raise ValueError(msg)
        return llm_data
    return []


@lru_cache(maxsize=1)
def _load_config() -> dict:
    """从 TOML 文件加载配置（已缓存）."""
    config_path = _get_config_path()
    if not config_path.is_file():
        return {}
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
    llm_providers = _normalize_llm_config(config)
    if not llm_providers:
        raise ValueError(
            "Configuration must contain at least one LLM provider in 'llm' array"
        )
    llm = llm_providers[0]
    return OpenAI(
        base_url=llm.get("base_url"),
        api_key=llm.get("api_key", ""),
    )


def get_benchmark_model_name() -> str:
    """从配置中获取基准测试模型名称."""
    config = _load_config()
    if "benchmark" in config:
        return config["benchmark"]["model"]
    llm_providers = _normalize_llm_config(config)
    if not llm_providers:
        raise ValueError("No LLM provider configured")
    return llm_providers[0]["model"]


def get_benchmark_temperature() -> float:
    """从配置中获取基准测试温度参数."""
    config = _load_config()
    if "benchmark" in config:
        return config["benchmark"].get("temperature", 0.0)
    llm_providers = _normalize_llm_config(config)
    if not llm_providers:
        return 0.7
    return llm_providers[0].get("temperature", 0.7)


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


def resolve_model_string(model_str: str) -> ResolvedModel:
    """解析模型引用 'provider/model?key=value' 格式.

    Args:
        model_str: 模型引用字符串，如 'deepseek/deepseek-chat?temperature=0.1'

    Returns:
        ResolvedModel 实例

    Raises:
        ValueError: 格式无效时
    """
    params: dict[str, Any] = {}
    if "?" in model_str:
        model_part, query_part = model_str.split("?", 1)
        for item in query_part.split("&"):
            if "=" in item:
                key, value = item.split("=", 1)
                try:
                    params[key] = float(value) if "." in value else int(value)
                except ValueError:
                    params[key] = value
        model_str = model_part

    if "/" not in model_str:
        raise ValueError(
            f"Invalid model string format: {model_str}. Expected 'provider/model'"
        )

    provider_name, model_name = model_str.split("/", 1)
    return ResolvedModel(
        provider_name=provider_name, model_name=model_name, params=params
    )
