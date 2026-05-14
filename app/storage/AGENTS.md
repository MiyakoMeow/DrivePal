# 数据存储

`app/storage/` —— 持久化存储引擎。

## 数据目录结构

```
data/
├── users/
│   └── {user_id}/
│       ├── events.jsonl          # 事件历史（JSONL）
│       ├── interactions.jsonl    # 交互记录（JSONL）
│       ├── feedback.jsonl        # 反馈记录（JSONL，MemoryBank 记忆强度反馈）
│       ├── feedback_log.jsonl    # 策略权重聚合源（JSONL，反馈学习原始记录）
│       ├── contexts.toml         # 上下文缓存（TOML）
│       ├── preferences.toml      # 用户偏好（TOML）
│       ├── strategies.toml       # 个性化策略 + reminder_weights（TOML）
│       ├── scenario_presets.toml # 场景预设（TOML）
│       └── memorybank/           # MemoryBank 持久化数据
│           ├── index.faiss
│           ├── metadata.json
│           └── extra_metadata.json
└── experiment_benchmark.toml  # 实验对比数据（全局共享）
```

旧平铺结构（`data/*.{jsonl,toml}`）通过 `init_storage()` 调用的模块级函数 `_migrate_legacy()` 幂等迁移至 `data/users/default/`。

## TOMLStore

`app/storage/toml_store.py`。异步锁 + 文件级粒度。

- **锁机制**：`_LOCK_REGISTRY` 全局字典，每个文件独立 `asyncio.Lock`
- **列表存储**：TOML 不支持顶层数组，用 `_list` 键包裹
- **None 处理**：`_clean_for_toml()` 递归将 `None` 转空字符串（含日志警告）
- **API**：
  - `read()` → T
  - `write(data: T)`
  - `append(item)` — 仅列表存储
  - `update(key, value)` — 仅字典存储
  - `merge_dict_key(key, updates)` — 合并字典的指定键（仅字典存储）

## 错误处理

| 异常类 | 触发条件 |
|--------|----------|
| `AppendError` | 非列表存储调用 `append()` |
| `UpdateError` | 非字典存储调用 `update()` |

## JSONLinesStore

`app/storage/jsonl_store.py`。JSONL 追加写，用于 events/interactions/feedback 等高频写入数据。

- **API**：
  - `append(obj: dict)` — 追加一行
  - `read_all()` → `list[dict]` — 读取所有行
  - `count()` → `int` — 文件行数（近似记录数）

## init_data

`app/storage/init_data.py`。数据目录初始化与默认数据填充。

- `_MIGRATED_FLAG = ".migrated_flag"` — 标记文件名。标记存在时 `init_storage()` 直接跳过迁移（幂等）
- `init_storage(data_dir: Path | None = None)` — 接受可选 data_dir，默认 `DATA_DIR`。创建 root → 检查 `_MIGRATED_FLAG` → 调用 `_migrate_legacy()` + `init_user_dir("default")` → 写标记（lifespan 使用）
- `init_user_dir(user_id)` → `Path` — 初始化指定用户的完整目录结构（4 个 jsonl + 4 个 toml 文件，`feedback_log.jsonl` 在 `init_user_dir()` 中直接创建）并写入默认值
- `_migrate_legacy()` → `bool` — 调用 `_migrate_text_files()` + `_migrate_memorybank()`，将平铺旧结构迁移至 `data/users/default/`。双重幂等保护：`default_dir.exists()` 提前返回 + `_MIGRATED_FLAG` 标记
- `_migrate_text_files(default_dir, old_root)` → `bool` — 迁移 3 个 jsonl + 4 个 toml 文件至 default_dir
- `_migrate_memorybank(default_dir, old_root)` — 迁移 `data/memorybank/` 和 `data/user_*/` 目录至 `data/users/{user_id}/` 结构

## experiment_store

`app/storage/experiment_store.py`。实验基准数据只读存储。通过 TOML 文件读取，无写入接口。

- `read_benchmark()` → `dict[str, Any]` — 读取 `experiment_benchmark.toml`，不存在返空 dict

## feedback_log

`app/storage/feedback_log.py`。策略权重反馈的原始记录存储，供 `strategies.toml` 中 `reminder_weights` 聚合计算。

- **文件名**：`feedback_log.jsonl`（与 `feedback.jsonl` 职责分离——后者服务于 MemoryBank 记忆强度反馈）
- **API**：
  - `append_feedback(user_dir, event_id, action, feedback_type)` — 追加一条反馈原始记录
  - `aggregate_weights(user_dir)` → `dict[str, float]` — 按事件类型聚合权重（accept +0.1 / ignore -0.1，新类型初始 0.5，范围 [0.1, 1.0]）
