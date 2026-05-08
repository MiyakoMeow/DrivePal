"""模型引用字符串解析."""

from typing import Any

from app.models.types import ResolvedModel


class InvalidModelStringError(ValueError):
    """无效的模型字符串格式错误."""

    def __init__(self, model_str: str) -> None:
        """初始化错误."""
        super().__init__(
            f"Invalid model string format: {model_str}. Expected 'provider/model'",
        )


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
                key, value_raw = item.split("=", 1)
                try:
                    params[key] = int(value_raw)
                except ValueError:
                    try:
                        params[key] = float(value_raw)
                    except ValueError:
                        params[key] = value_raw
        model_str = model_part

    if "/" not in model_str:
        raise InvalidModelStringError(model_str)

    provider_name, model_name = model_str.split("/", 1)
    return ResolvedModel(
        provider_name=provider_name,
        model_name=model_name,
        params=params,
    )
