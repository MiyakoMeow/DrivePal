# 数据存储

`app/storage/` — 持久化引擎。

## 数据目录

```
data/
├── users/{user_id}/
│   ├── events.jsonl           # 事件历史
│   ├── interactions.jsonl     # 交互记录
│   ├── feedback.jsonl         # MemoryBank记忆强度反馈
│   ├── feedback_log.jsonl     # 策略权重聚合源
│   ├── contexts.toml          # 上下文缓存
│   ├── preferences.toml       # 用户偏好
│   ├── strategies.toml        # 个性化策略 + reminder_weights
│   ├── scenario_presets.toml  # 场景预设
│   └── memorybank/            # MemoryBank持久化
│       ├── index.faiss
│       ├── metadata.json
│       └── extra_metadata.json
└── experiment_benchmark.toml  # 实验对比（全局共享）
```

旧平铺结构由 `init_storage()` 调用 `_migrate_legacy()` 幂等迁移至 `data/users/default/`。

## TOMLStore (`toml_store.py`)

异步锁+文件级粒度。

- **锁**：`_LOCK_REGISTRY` 每文件独立 `asyncio.Lock`
- **列表存储**：`_list` 键包裹（TOML不支持顶层组数）
- **None处理**：`_clean_for_toml()` 递归转空字符串
- **API**：read/write/append(列表)/update(字典)/merge_dict_key(字典)

### 异常

| 异常 | 触发 |
|------|------|
| AppendError | 非列表存储调append |
| UpdateError | 非字典存储调update/merge_dict_key |

## JSONLinesStore (`jsonl_store.py`)

JSONL追加写，用于高频写入数据(events/interactions/feedback)。

- append(obj) / read_all() / count()

## init_data (`init_data.py`)

`init_storage(data_dir)` 创建目录 + `_migrate_legacy()` + `init_user_dir("default")`。
`init_user_dir(user_id)` 创建4个jsonl + 4个toml文件并写默认值。
`_MIGRATED_FLAG` 标记保证幂等。

## experiment_store (`experiment_store.py`)

只读。`read_benchmark()` 读 `experiment_benchmark.toml`，不存在返空dict。

## feedback_log (`feedback_log.py`)

策略权重反馈原始记录。与 `feedback.jsonl`（MemoryBank记忆强度）职责分离。

- `append_feedback(user_dir, event_id, action, feedback_type)` — 追加原始记录
- `aggregate_weights(user_dir)` — 按类型聚合（accept +0.1/ignore -0.1，基值0.5，范围[0.1, 1.0]）
