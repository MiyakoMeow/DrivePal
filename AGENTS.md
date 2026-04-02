# 知行车秘

## 项目配置

- 完全使用`uv`进行依赖管理、实际项目运行等。

- 检查配置：[详见CI](.github/workflows/python.yml)
  - 每次修改后：
    1. `uv run ruff check --fix`
    2. `uv run ty check`
    3. `uv run ruff format`
  - 任务完成后：
    1. 额外运行CI中的`test`检查，详细验证无功能破坏。
  - 注意：
    1. 本项目的类型检查器，使用`ty`，而不是`mypy`、`pyright`等。[官方文档](https://docs.astral.sh/ty/)。

## 锁使用规则

- **只允许**在以 `_locked_` 开头的内部方法中使用 `asyncio.Lock`
- **禁止**在公共API方法中直接使用锁
- 公共API通过调用对应的 `_locked_` 方法间接获得线程安全
- TOMLStore 等底层存储的内部锁机制作为实现细节，不受此规则约束
