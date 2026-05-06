# 知行车秘

本科毕设项目。

## 项目配置

`Python 3.14` + `uv`。

### Nix 环境提示

NixOS 下若运行/测试异常，用 `nix develop --command` 包裹命令。

## 检查流程

每次改后：
1. `uv run ruff check --fix`
2. `uv run ruff format`
3. `uv run ty check`

任务完：
1. `uv run pytest`

### Python 3.14 注意

`except ValueError, TypeError:` 是 PEP-758 新语法（逗号分隔多异常），非 Python 2 残留。ruff 已默认不禁。

## 代码规范

### 注释

中文。

### 提交信息

英文。Conventional Commits 格式。

### 内联抑制

**禁** `# noqa`、`# type:`。CI `.github/workflows/no-suppressions.yml` 扫描报错。
遇 lint/type 错误：
1. 修代码
2. 修不了 → `ruff.toml` / `ty.toml` 按文件或全局忽略，注明原因

## 文档索引

- `README.md` — 概述、功能、快速开始
- `DEV.md` — 开发指南、API、测试、MemoryBank 实现分析
