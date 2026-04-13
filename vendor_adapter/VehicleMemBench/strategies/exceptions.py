"""VehicleMemBench 策略模块异常定义."""


class VehicleMemBenchError(Exception):
    """VehicleMemBench 模块的基准错误."""

    def __init__(
        self,
        message: str,
        *,
        file_num: int | None = None,
        memory_type: str | None = None,
    ) -> None:
        """初始化基准测试错误.

        Args:
            message: 错误信息.
            file_num: 关联的文件编号.
            memory_type: 关联的记忆类型.

        """
        self.file_num = file_num
        self.memory_type = memory_type
        super().__init__(message)
