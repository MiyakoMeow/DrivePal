# app/storage - 数据存储引擎

## TOMLStore（toml_store.py）

异步锁 + 文件级粒度。

- **锁机制**：`_LOCK_REGISTRY` 全局字典，每个文件独立 `asyncio.Lock`
- **列表存储**：TOML 不支持顶层数组，用 `_list` 键包裹
- **None 处理**：`_clean_for_toml()` 递归将 `None` 转空字符串（含日志警告）
- **异常**：`AppendError`（非列表调 append）/ `UpdateError`（非字典调 update）
- **API**：`read()` / `write()` / `append(item)` / `update(key, value)`

## JSONLStore（jsonl_store.py）

JSONL 追加写，用于高频写入数据（events、interactions、feedback、experiment_results）。

## init_data.py

数据目录初始化 + 旧平铺结构迁移（`_migrate_legacy()` 幂等迁移至 `data/users/default/`）。
