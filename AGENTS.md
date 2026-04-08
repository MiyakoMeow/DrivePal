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

## Nix 开发环境

项目提供了 `flake.nix`，包含 Python 3.14、uv 和 CUDA 12.8 依赖。

```bash
# 直接运行命令（避免进入 shell）
nix develop -c uv run main.py
```

## 注意事项

### Python 3.14+ 语法差异

本项目运行在 Python 3.14+，以下语法与低版本行为不同，需特别注意：

- **`except X, Y:` 元组捕获**（[PEP 758](https://peps.python.org/pep-0758/)）：等效于 `except (X, Y):`，同时捕获多种异常。ruff formatter 会主动将括号形式还原为逗号形式，这是预期行为，不要修改。
- **`except* E:` 异常组**（[PEP 654](https://peps.python.org/pep-0654/)）：用于捕获 `ExceptionGroup` / `BaseExceptionGroup`，语法为 `except* ValueError as eg:`。
- **`type` 类型别名语句**（[PEP 695](https://peps.python.org/pep-0695/)）：Python 3.12+ 支持 `type Alias = int`，3.12+ 支持泛型 `type Gen[T] = list[T]`。本项目可直接使用。
- **延迟求值注解**（[PEP 649](https://peps.python.org/pep-0649/) / [PEP 749](https://peps.python.org/pep-0749/)）：Python 3.14 起注解采用延迟求值语义（访问时才求值为真实 Python 对象，而非字符串），通常无需手动添加 `from __future__ import annotations`。

## Skill流程特定配置

### brainstorming

- 编写 `设计文档（spec）` 和 `计划文档（plan）` 完成后，运行完整的 review loop 流程。
- 优先选择 `SubAgent-Driven Development` 。每一步完成后，同样运行 review loop 流程。
