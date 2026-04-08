"""基准测试模型客户端配置."""

import os

import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from openai import OpenAI

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.embedding import EmbeddingModel
    from app.models.chat import ChatModel

from app.models.settings import ResolvedModel


@dataclass(frozen=True)
class BenchmarkConfig:
    """基准测试配置（一次性提取所有字段）."""

    base_url: str
    api_key: str
    model: str
    temperature: float
    max_tokens: int


def _get_config_path() -> Path:
    """获取配置文件路径，支持环境变量覆盖."""
    env_path = os.environ.get("CONFIG_PATH", "config/llm.toml")
    if Path(env_path).is_absolute():
        return Path(env_path)
    return Path(__file__).resolve().parent.parent.parent / env_path


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


def get_store_chat_model() -> ChatModel:
    """获取用于记忆存储操作的聊天模型."""
    from app.models.settings import get_chat_model

    return get_chat_model()


def _resolve_provider(provider_name: str) -> dict:
    """根据 provider 名称解析 provider 配置.

    Args:
        provider_name: provider 名称，对应 model_providers 中的表名

    Returns:
        provider 配置字典

    Raises:
        ValueError: provider 未配置时

    """
    config = _load_config()
    providers = config.get("model_providers", {})
    if provider_name not in providers:
        raise ValueError(f"Provider '{provider_name}' not found in model_providers")
    return providers[provider_name]


def get_model_group_providers(name: str) -> list[dict]:
    """按组名获取 LLMProviderConfig 字典列表（底层接口）.

    Args:
        name: 模型组名称

    Returns:
        LLMProviderConfig 字典列表

    Raises:
        KeyError: 模型组不存在时

    """
    config = _load_config()
    model_groups = config.get("model_groups", {})
    if name not in model_groups:
        raise KeyError(f"Model group '{name}' not found")

    model_refs = model_groups[name].get("models", [])
    if not model_refs:
        return []

    result = []
    for ref in model_refs:
        resolved = resolve_model_string(ref)
        provider_config = _resolve_provider(resolved.provider_name)
        api_key_env = provider_config.get("api_key_env")
        if api_key_env:
            api_key: str = os.environ.get(api_key_env, "")
        else:
            api_key = provider_config.get("api_key", "")
        result.append(
            {
                "model": resolved.model_name,
                "base_url": provider_config.get("base_url"),
                "api_key": api_key,
                "temperature": resolved.params.get("temperature", 0.7),
            }
        )
    return result


def get_store_embedding_model() -> EmbeddingModel:
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
