# JSON to TOML 存储迁移设计

## 概述

将项目中的配置文件（config/）和记忆存储（data/）从 JSON 格式迁移至 TOML 格式。

## 范围

### 配置文件
| 文件 | 用途 |
|------|------|
| config/llm.json | LLM 模型配置 |
| config/driver_states.json | 驾驶状态定义 |
| config/scenarios.json | 场景模板定义 |

### 记忆存储
| 文件 | 用途 |
|------|------|
| data/events.json | 事件记录 |
| data/interactions.json | 交互记录 |
| data/contexts.json | 上下文数据 |
| data/preferences.json | 用户偏好 |
| data/feedback.json | 反馈数据 |
| data/strategies.json | 策略配置 |
| data/experiment_results.json | 实验结果 |
| data/memorybank_summaries.json | 记忆银行摘要 |

## 迁移策略

一次性整体迁移：直接替换 JSONStore 为 TOMLStore，扩展名统一改为 .toml。

迁移完成后删除所有旧 .json 文件，不保留备份。

现有数据将完整转换到 TOML 文件中。

## 架构

### 新增文件

**`app/storage/toml_store.py`**

```python
class TOMLStore:
    """基于 TOML 文件的通用存储引擎，接口与 JSONStore 一致。"""
```

实现要点：
- 读取使用 Python 标准库 `tomllib`（Python 3.11+）
- 写入使用 `tomli-w` 库（TOML writer，与 tomllib 配套）
- 保留文件锁机制（`_LOCK_REGISTRY`）
- 文件不存在时自动创建空结构

### 修改文件

| 文件 | 变更 |
|------|------|
| `app/storage/toml_store.py` | 新增 |
| `app/storage/init_data.py` | 扩展名从 .json 改为 .toml，数据结构转为 TOML 格式 |
| `app/agents/workflow.py` | JSONStore → TOMLStore，strategies.json → strategies.toml |
| `app/memory/components.py` | JSONStore → TOMLStore，多处 .json → .toml |
| `app/memory/stores/memory_bank_store.py` | JSONStore → TOMLStore |
| `app/models/settings.py` | CONFIG_PATH 环境变量默认值改为 .toml |
| `adapters/model_config.py` | CONFIG_PATH 环境变量默认值改为 .toml |
| `tests/test_components.py` | JSONStore → TOMLStore |
| `tests/test_storage.py` | JSONStore → TOMLStore |
| `tests/test_model_config.py` | .json → .toml |
| `tests/test_settings.py` | .json → .toml |

### 删除文件

| 文件 | 原因 |
|------|------|
| `app/storage/json_store.py` | 功能已被 TOMLStore 替代 |

### 依赖变更

新增 `tomli-w` 依赖（TOML 写入库）：

```toml
[project.optional-dependencies]
toml-write = ["tomli-w"]
```

或使用 `pip install tomli-w`。

## 数据转换

### init_data.py 默认数据 TOML 格式

```toml
[strategies]
preferred_time_offset = 15
preferred_method = "visual"

[strategies.reminder_weights]
[strategies.cooldown_periods]

[strategies.ignored_patterns]
[strategies.modified_keywords]

[memorybank_summaries]
daily_summaries = {}
overall_summary = ""
```

### 列表类型数据

如 `events.json` → `events.toml`，内容为 TOML 数组：

```toml
[[events]]
# 事件条目
```

## 错误处理

| 场景 | 处理方式 |
|------|----------|
| 文件不存在 | 自动创建父目录，写入空结构 |
| 解析错误 | 抛出 `tomllib.TOMLDecodeError` |
| 并发写入 | 通过 `asyncio.Lock` 实现文件锁 |

## 实现步骤

1. 安装 `tomli-w` 依赖
2. 创建 `app/storage/toml_store.py`
3. 更新 `app/storage/init_data.py` 使用 .toml 扩展名和 TOML 格式
4. 更新 `app/agents/workflow.py` - TOMLStore 导入和 .toml 扩展名
5. 更新 `app/memory/components.py` - TOMLStore 导入和 .toml 扩展名
6. 更新 `app/memory/stores/memory_bank_store.py` - TOMLStore 导入
7. 更新 `app/models/settings.py` - 默认配置路径 .toml
8. 更新 `adapters/model_config.py` - 默认配置路径 .toml
9. 更新测试文件：
   - `tests/test_components.py`
   - `tests/test_storage.py`
   - `tests/test_model_config.py`
   - `tests/test_settings.py`
10. 运行 `uv run ruff check --fix && uv run ty check && uv run ruff format`
11. 运行 `uv run pytest` 验证功能
12. 删除 `app/storage/json_store.py`
13. 确认所有 .json 文件已迁移后，删除 config/ 和 data/ 目录下的 .json 文件

## 回滚计划

若迁移失败：
1. 从 git 恢复 `app/storage/json_store.py`
2. 恢复各文件中 .json 引用
3. 已删除的 .json 文件可从 git 历史恢复

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| TOML 格式更严格，注释、多行字符串等可能出错 | 使用标准库解析器，确保数据符合 TOML 规范 |
| 现有代码硬编码 .json 扩展名 | 通过搜索确认所有引用已更新 |
| 并发写入冲突 | 保留现有锁机制 |
| 迁移后数据丢失 | 步骤11的测试验证通过后再删除旧文件 |
