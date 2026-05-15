"""DrivePal × VehicleMemBench 评估适配器.

子命令:
    run-all     — 全量运行 5 组（none+gold+summary+key_value+drivepal）
    model       — 单组模型评测（none/gold/summary/key_value）
    memory-add  — 写入 benchmark 历史至 DrivePal MemoryBank
    memory-test — 使用 DrivePal MemoryBank 运行评测

结果存储至 data/vehicle_mem_bench/，命名与原项目一致:
    {prefix}_{model}_{timestamp}/   （模型评测）
    {prefix}_{system}_{model}_{timestamp}/ （记忆评测）

模型参数（--api-base / --api-key / --model）不传时自动从 config/llm.toml 读取。
"""

__all__ = []
