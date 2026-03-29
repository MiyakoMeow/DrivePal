import json
import os
from pathlib import Path

from openai import OpenAI

CONFIG_PATH = str(Path(__file__).resolve().parent.parent / "config" / "llm.json")


def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def get_benchmark_client() -> OpenAI:
    config = _load_config()
    if "benchmark" in config:
        bc = config["benchmark"]
        api_key = os.environ.get(bc.get("api_key_env", ""), bc.get("api_key", ""))
        return OpenAI(
            base_url=bc["base_url"],
            api_key=api_key,
        )
    llm = config["llm"][0]
    return OpenAI(
        base_url=llm.get("base_url"),
        api_key=llm.get("api_key", ""),
    )


def get_benchmark_model_name() -> str:
    config = _load_config()
    if "benchmark" in config:
        return config["benchmark"]["model"]
    return config["llm"][0]["model"]


def get_benchmark_temperature() -> float:
    config = _load_config()
    if "benchmark" in config:
        return config["benchmark"].get("temperature", 0.0)
    return config["llm"][0].get("temperature", 0.7)


def get_benchmark_max_tokens() -> int:
    config = _load_config()
    if "benchmark" in config:
        return config["benchmark"].get("max_tokens", 8192)
    return 8192


def get_store_chat_model():
    from app.models.settings import get_chat_model

    return get_chat_model()


def get_store_embedding_model():
    from app.models.settings import get_embedding_model

    return get_embedding_model()
