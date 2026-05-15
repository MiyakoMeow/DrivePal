# 数据存储

`app/storage/` — 持久化引擎。

## 数据目录

```mermaid
flowchart LR
    D["data/"]
    subgraph User["users/{user_id}/"]
        direction LR
        E["events.jsonl<br/>事件历史"]
        I["interactions.jsonl<br/>交互记录"]
        F["feedback.jsonl<br/>记忆强度反馈"]
        FL["feedback_log.jsonl<br/>权重聚合源"]
        CT["contexts.toml<br/>上下文缓存"]
        PR["preferences.toml<br/>用户偏好"]
        ST["strategies.toml<br/>个性化策略"]
        SP["scenario_presets.toml<br/>场景预设"]
        subgraph MB["memorybank/"]
            FA["index.faiss"]
            MD["metadata.json"]
            EM["extra_metadata.json"]
        end
    end
    EB["experiment_benchmark.toml<br/>实验对比"]
    D --> User
    D --> EB
```

旧平铺结构由 `init_storage()` 调用 `_migrate_legacy()` 幂等迁移。迁移范围：
- `data/*.jsonl`、`data/*.toml` → `data/users/default/`
- `data/memorybank/` → `data/users/default/memorybank/`（整体目录）
- `data/memorybank/user_{id}/` → `data/users/{id}/memorybank/`（按用户拆分）
- `data/user_{id}/`（平铺目录）→ `data/users/{id}/`（按用户拆分）

## TOMLStore (`toml_store.py`)

异步锁+文件级粒度。

- **锁**：`_LOCK_REGISTRY` 每文件独立 `asyncio.Lock`
- **列表存储**：`_list` 键包裹（TOML不支持顶层组数）
- **None处理**：`_clean_for_toml()` 递归转空字符串
- **`default_factory`**：`__init__` 可选参数，控制文件不存在时写入的默认值。默认 `dict`，传 `list` 以支持列表模式
- **API**：read/write/append(列表)/update(字典)/merge_dict_key(字典)

### 异常（独立异常，不入 AppError 继承树）

| 异常 | 父类 | 触发 |
|------|------|------|
| `AppendError` | `TypeError` | 非列表存储调 append |
| `UpdateError` | `TypeError` | 非字典存储调 update/merge_dict_key |

性质：结构误用（调用了当前存储模式不支持的 API），非域内业务错误。继承 `TypeError` 而非 `AppError`，不经过 API `safe_call()` 映射路径。

## JSONLinesStore (`jsonl_store.py`)

JSONL追加写，用于高频写入数据(events/interactions/feedback)。

- append(obj) / read_all() / count()

## init_data (`init_data.py`)

`init_storage(data_dir)` 创建目录 + `_migrate_legacy()` + `init_user_dir("default")`。
`init_user_dir(user_id)` 创建4个jsonl + 4个toml文件并写默认值。默认值：
- `preferences.toml`：`{"language": "zh-CN"}`
- `strategies.toml`：6字段 — `preferred_time_offset: 15`、`preferred_method: "visual"`、`reminder_weights: {}`、`ignored_patterns: []`、`modified_keywords: []`、`cooldown_periods: {}`
- `scenario_presets.toml`：`{"_list": []}`
`_MIGRATED_FLAG` 标记保证幂等。

## experiment_store (`experiment_store.py`)

只读。`read_benchmark()` 读 `experiment_benchmark.toml`，不存在返空dict。

## feedback_log (`feedback_log.py`)

策略权重反馈原始记录。与 `feedback.jsonl`（MemoryBank记忆强度）职责分离。

- `append_feedback(user_dir, event_id, action, feedback_type)` — 追加原始记录
- `aggregate_weights(user_dir)` — 按类型聚合（accept +0.1/ignore -0.1/modify +0.05/snooze 0.0，基值0.5，范围[0.1, 1.0]）
