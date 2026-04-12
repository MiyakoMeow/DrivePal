"""模型相关的纯数据类型定义，不依赖其他 app 模块."""

from dataclasses import dataclass
from typing import Any


@dataclass
class ResolvedModel:
    """解析后的模型引用."""

    provider_name: str
    model_name: str
    params: dict[str, Any]


@dataclass
class ProviderConfig:
    """LLM 提供商基础配置."""

    model: str
    base_url: str | None = None
    api_key: str | None = None
