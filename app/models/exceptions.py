"""模型相关异常定义."""


class ProviderNotFoundError(ValueError):
    """Provider 未找到错误."""

    def __init__(self, provider_name: str) -> None:
        """初始化错误."""
        super().__init__(f"Provider '{provider_name}' not found in model_providers")


class ModelGroupNotFoundError(KeyError):
    """模型组未找到错误."""

    def __init__(self, name: str) -> None:
        """初始化错误."""
        super().__init__(f"Model group '{name}' not found")
