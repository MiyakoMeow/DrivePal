"""MemoryBank 异常体系——三层：基类 → 瞬态/永久 → 具体。"""


class MemoryBankError(Exception):
    """MemoryBank 异常基类。"""


class TransientError(MemoryBankError):
    """可重试的瞬态错误（网络、超时、限速）。"""

    def __init__(self, message: str, retry_after: float = 1.0) -> None:
        """初始化瞬态错误。

        Args:
            message: 错误描述。
            retry_after: 建议重试间隔（秒）。

        """
        super().__init__(message)
        self.retry_after = retry_after


class FatalError(MemoryBankError):
    """不可恢复的永久错误（配置、数据损坏）。"""


class LLMCallFailedError(TransientError):
    """LLM 调用失败（可重试）。"""


class SummarizationEmpty(MemoryBankError):
    """LLM 返回空内容——非错误，哨兵异常。调用方捕获后返回 None。"""


class ConfigError(FatalError):
    """配置错误。"""


class IndexIntegrityError(FatalError):
    """FAISS 索引文件损坏，不可读取。"""
