"""全系统异常基类。各模块异常继承此类实现统一异常体系。"""


class AppError(Exception):
    """全系统异常基类。

    携带机器可读 code + 人类可读 message。
    API 层 safe_call() 按子类型映射 HTTP 状态码。
    各模块异常（MemoryBankError/ChatError/ToolExecutionError/WorkflowError）继承此类。
    API 层 AppError(HTTPException) 也多重继承此类。
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)
