# 数据存储

`app/storage/` —— 持久化存储引擎。

## 数据目录结构

```
data/
├── users/
│   └── {user_id}/
│       ├── events.jsonl          # 事件历史（JSONL）
│       ├── interactions.jsonl    # 交互记录（JSONL）
│       ├── feedback.jsonl        # 反馈记录（JSONL）
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

旧平铺结构（`data/*.jsonl`）通过 `init_storage()` 中的 `_migrate_legacy()` 幂等迁移至 `data/users/default/`。

## TOMLStore

`app/storage/toml_store.py`。异步锁 + 文件级粒度。

- **锁机制**：`_LOCK_REGISTRY` 全局字典，每个文件独立 `asyncio.Lock`
- **列表存储**：TOML 不支持顶层数组，用 `_list` 键包裹
- **None 处理**：`_clean_for_toml()` 递归将 `None` 转空字符串（含日志警告）
- **异常**：`AppendError`（非列表调 append）/ `UpdateError`（非字典调 update）
- **API**：
  - `read()` → T
  - `write(data: T)`
  - `append(item)` — 仅列表存储
  - `update(key, value)` — 仅字典存储

## JSONLStore

`app/storage/jsonl_store.py`。JSONL 追加写，用于 events/interactions/feedback/experiment_results 等高频写入数据。
