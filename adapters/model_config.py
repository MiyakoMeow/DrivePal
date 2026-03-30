"""基准测试模型客户端配置."""

import json
import os
from pathlib import Path

from openai import OpenAI

CONFIG_PATH = str(Path(__file__).resolve().parent.parent / "config" / "llm.json")


def _load_config() -> dict:
    """从 JSON 文件加载配置."""
    with open(CONFIG_PATH) as f:
        return json.load(f)


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


def get_store_chat_model():
    """获取用于记忆存储操作的聊天模型."""
    from app.models.settings import get_chat_model

    return get_chat_model()


def get_store_embedding_model():
    """获取用于记忆存储操作的嵌入模型."""
    from app.models.settings import get_embedding_model

    return get_embedding_model()
