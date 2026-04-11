"""模型模块共享类型定义."""

from dataclasses import dataclass
from typing import Any


@dataclass
class ResolvedModel:
    """解析后的模型引用."""

    provider_name: str
    model_name: str
    params: dict[str, Any]
