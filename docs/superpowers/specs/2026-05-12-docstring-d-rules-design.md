# 修复 ruff Dxxx docstring 规则

## 目标

从 ruff.toml 全局 ignore 移除 D400、D211、D212 规则，不再靠 ignore 回避 docstring 规则。
D415 保留 ignore（与 D400 冗余）。

## 方案

### 策略选择

| 规则 | 行动 | 理由 |
|------|------|------|
| D203 | 留 ignore | 与 D211 冲突——项目选 D211（class docstring 前无空行） |
| D211 | 移出 ignore | 项目风格，当前 0 违规 |
| D213 | 留 ignore | 与 D212 冲突——D212（摘要第一行）已激活且 0 违规 |
| D400 | 移出 ignore | 首行句号——全代码库 fix 违规 |
| D415 | 留 ignore | 与 D400 冗余（D400 是 D415 超集） |

### 修复范围

全代码库 D400 违规统一修复。文件分布：

| 目录 | 违规数 | 处理方式 |
|------|--------|----------|
| `app/` | ~29 | 加句号 |
| `tests/` | ~27 | 加句号 |
| `scripts/` | ~26 | 加句号 |
| `experiments/` | 含于 scripts 计数中 | 加句号 |

### ruff.toml 变更

- 从全局 ignore 移除 `D211`（项目选此风格，0 违规）
- `D212` 已在生效中（当前不在 ignore 列表，0 违规），无需变更
- 从全局 ignore 移除 `D400`（修复违规后依此规则）
- `D415` 保留在全局 ignore，注释改为「与 D400 冗余」
- 更新 `D203` 注释为「与 D211 冲突——项目选 D211」
- 更新 `D213` 注释为「与 D212 冲突——项目选 D212，D212 已生效」

### 执行步骤

1. 建工作树 `fix/docstring-d-rules`
2. 改 `ruff.toml`
3. `ruff check --fix --select=D400 .` 自动修复 D400 违规（docstring 首行加句号）
4. `ruff check --select=D --output-format concise .` 验证零违规
5. `ruff format --check .` + `ruff check .` + `uv run ty check` + `uv run pytest`
6. commit

### 未解决问题

无。
