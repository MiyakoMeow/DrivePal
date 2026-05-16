"""DrivePal × VehicleMemBench 评估适配器.

子命令（无子命令时默认等价于 run）:
    run         — 默认仅跑 drivepal 组；--all 全量 5 组
    model       — 单组模型评测（none/gold/summary/key_value）
    memory-add  — 写入 benchmark 历史至 DrivePal MemoryBank
    memory-test — 使用 DrivePal MemoryBank 运行评测

结果存储至 data/vehicle_mem_bench/，命名与原项目一致:
    {prefix}_{model}_{timestamp}/   （模型评测）
    {prefix}_{system}_{model}_{timestamp}/ （记忆评测）

模型参数（--api-base / --api-key / --model）不传时自动从 config/llm.toml 读取。
"""

__all__ = []
