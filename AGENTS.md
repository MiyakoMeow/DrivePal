# 知行车秘

## 项目配置

- 使用`uv`。

- 检查配置：[详见CI](.github/workflows/python.yml)
  - 每次修改后，直接运行，不要加额外参数：
    1. `uv run ruff check --fix`
    2. `uv run ruff format`
    3. `uv run ty check`
  - 任务完成后：
    1. 额外运行CI中的 `test` 检查，详细验证无功能破坏。
  - 注意：
    1. 本项目的类型检查器，使用 `ty` 。[官方文档](https://docs.astral.sh/ty/)

## 代码规范

### 代码注释

- 必须使用中文。

### 提交信息

- 必须使用英文。
- 必须遵循 Conventional Commits 规范。

### PEP参考

- PEP 585
- PEP 604
- PEP 649
- PEP 654
- PEP 695
- PEP 758

