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

## Python风格

- 异常处理：支持Python 3.14新语法 `except (ValueError, TypeError) as e:` 和旧式逗号语法 `except ValueError, e:`，两者皆可。

## Skill流程特定配置

### brainstorming

- 编写 `设计文档（spec）` 和 `计划文档（plan）` 完成后，运行完整的 review loop 流程。
- 优先选择 `SubAgent-Driven Development` 。每一步完成后，同样运行 review loop 流程。
