"""模型引用字符串解析和配置加载."""

import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.models.exceptions import ModelGroupNotFoundError, ProviderNotFoundError
from app.models.types import ResolvedModel


class InvalidModelStringError(ValueError):
    """无效的模型字符串格式错误."""

    def __init__(self, model_str: str) -> None:
        """初始化错误."""
        super().__init__(
            f"Invalid model string format: {model_str}. Expected 'provider/model'",
        )


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
        raise ProviderNotFoundError(provider_name)
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
        raise ModelGroupNotFoundError(name)

    model_refs = model_groups[name].get("models", [])
    if not model_refs:
        return []

    result = []
    for ref in model_refs:
        resolved = resolve_model_string(ref)
        provider_config = _resolve_provider(resolved.provider_name)
        api_key_env = provider_config.get("api_key_env")
        if api_key_env:
            api_key: str | None = os.environ.get(api_key_env, "")
        else:
            api_key = provider_config.get("api_key")
        result.append(
            {
                "model": resolved.model_name,
                "base_url": provider_config.get("base_url"),
                "api_key": api_key,
                "temperature": resolved.params.get("temperature", 0.7),
            },
        )
    return result


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
        raise InvalidModelStringError(model_str)

    provider_name, model_name = model_str.split("/", 1)
    return ResolvedModel(
        provider_name=provider_name,
        model_name=model_name,
        params=params,
    )
