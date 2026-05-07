# 记忆系统改进：补齐缺失功能

## 概述

基于 VehicleMemBench MemoryBank 实现与当前 DrivePal 记忆系统的差异分析，补齐影响生产可靠性和正确性的缺失功能。

## 改动清单

### 1. EmbeddingClient — 弹性 embedding 封装

**新文件：** `app/memory/embedding_client.py`

Robust wrapper 对标 `LlmClient`，封装重试/退避/分批逻辑。

```
EmbeddingClient
├── __init__(embedding_model, *, rng)
├── encode(text: str) → list[float]         单条，带重试
└── encode_batch(texts: list[str]) → list[list[float]]  分批+重试
```

**重试策略：**
- 最大重试 5 次
- 指数退避 `2^attempt + jitter`
- 瞬态错误识别：连接/超时/限速/5xx
- 非瞬态错误（4xx）：立即抛出
- 分批上限 100（BATCH_SIZE 可配置）

**受影响文件：**

| 文件 | 改动 |
|------|------|
| `app/memory/memory_bank/store.py` | 构造参数增 `embedding_client`；未提供时从 `embedding_model` 包装；`.encode()` → client 调用 |
| `app/memory/memory_bank/retrieval.py` | `__init__` 接收 `embedding_client` 替代 `embedding_model` |

### 2. 遗忘引用日期

`MemoryBankStore` 增加 `reference_date: str | None = None` 构造参数。
`_purge_forgotten` 和 `_forget_at_ingestion` 使用此值代替 `datetime.now(UTC)`。
若为 `None` 回退现有行为（`now()`）。

**受影响文件：** `app/memory/memory_bank/store.py`

### 3. `_next_id` 同步

`FaissIndex.remove_vectors` 在重建 `_id_to_meta` 后同步 `_next_id = max(...) + 1`。
防御性修正，对齐 VehicleMemBench 行为。

**受影响文件：** `app/memory/memory_bank/faiss_index.py`

### 4. 嵌入维度不匹配处理

当前行为：静默重建索引 + 清空元数据。
改为：日志警告 + 抛出 `ValueError`，由调用者决定是否清数据重来。

**受影响文件：** `app/memory/memory_bank/faiss_index.py`

### 5. JSON null 防御

- `FaissIndex.load()`：加载 `extra_metadata.json` 后做 `isinstance(extra, dict)` 校验
- `FaissIndex.get_extra()`：`None` 或非 dict 时返回空 dict

**受影响文件：** `app/memory/memory_bank/faiss_index.py`

## 不变的部分

- 不引入多用户隔离（单用户场景不需要）
- 不改动 `ForgettingCurve` / `compute_ingestion_forget_ids` 接口（已有 `reference_date` 参数）
- 不改动 `LlmClient`（已有完整重试）
- 不改动 `Summarizer`（调用链不受影响）

## 实现注意事项

- `RetrievalPipeline` 的 `__init__` 参数从 `embedding_model` 改为 `embedding_client`（破坏性变更）。
  需排查所有构造调用点（当前仅 `store.py:MemoryBankStore.__init__` 一处，`singleton.py` 不受影响）。

## 测试策略

- `EmbeddingClient`：mock `EmbeddingModel.encode()`，验证重试次数、退避、错误分类
- `Store`：验证 `reference_date` 传递到遗忘方法
- `FaissIndex`：验证 `_next_id` 同步、维度不匹配异常、null extra 防御
- 现有测试全绿
