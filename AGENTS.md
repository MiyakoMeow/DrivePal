# 知行车秘

- 本科毕业设计项目。

## 项目配置

- 使用 `Python 3.14` + `uv`。

## 检查配置：

- 每次修改后：
  1. `uv run ruff check --fix`（不要加参数）
  2. `uv run ruff format`（不要加参数）
  3. `uv run ty check`（不要加参数）

- 任务完成后：
  1. `uv run pytest`（不要加参数）

## 代码规范

### 代码注释

- 必须使用中文。

### 提交信息

- 必须使用英文。
- 必须遵循 Conventional Commits 规范。

## 文档索引

- `README.md` — 项目概述、功能介绍、快速开始指南
- `DEV.md` — 开发指南（配置、API、测试）及 MemoryBank 实现差异分析

