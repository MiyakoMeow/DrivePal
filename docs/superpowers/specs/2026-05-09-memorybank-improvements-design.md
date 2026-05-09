# MemoryBank 改进设计

## 背景

对比 DrivePal `app/memory/memory_bank/` 与 VehicleMemBench `evaluation/memorysystems/memorybank.py` 两套实现，算法层面（遗忘公式、检索管道四阶段、自适应分块、说话人降权、邻居合并、LLM prompt）完全一致，差异集中在工程层面。本文档规划四轮渐进式改进。

## B1：行为对齐

目标：DrivePal 在同等输入下的行为与 VMB 不可区分。

### 1.1 LLM 温度对齐

**文件：** `app/memory/memory_bank/summarizer.py`

**现状：** `_SUMMARY_DEFAULT_TEMPERATURE = 0.3`。VMB 摘要用 `LLM_TEMPERATURE = 0.7`。
prompt 一字不差，温度差 0.4 导致摘要内容显著不同。

**改法：** 默认值改为 `0.7`。仍可通过环境变量 `MEMORYBANK_LLM_TEMPERATURE` 覆盖。

```python
_SUMMARY_DEFAULT_TEMPERATURE = 0.7  # was 0.3
```

### 1.2 摘要触发时机

**文件：** `app/memory/memory_bank/lifecycle.py`, `app/memory/memory_bank/store.py`

**现状：** 每次 `write()` 后通过 `_post_write_forget_and_summarize()` 立即触发后台摘要。
Inflight 锁阻止同日期重复，但"第一条消息触发摘要→该日后续消息未包含"问题存在。

**VMB 行为：** 全天数据全部摄入 → 一次性串行调用 4 种摘要/人格/遗忘。

**改法：**

1. 从 `write()` 和 `write_interaction()` 中移除 `_trigger_background_summarize(date_key)` 调用。
2. 新增 `MemoryBankStore.finalize_ingestion() → None`：
   - 收集 metadata 中所有唯一 `source` 值（来源：`add_vector` 的 `extra_meta={"source": date_key}`）
   - 对每个无摘要的日期调用对应 summary/personality 生成器
   - 执行一次性摄入遗忘 `_forget_at_ingestion()`
   - 持久化索引

3. `MemoryLifecycle` 新增 `finalize()` 方法封装以上逻辑。

**接口：**

```python
# store.py
async def finalize_ingestion(self) -> None:
    """摘要 + 遗忘 + 持久化。应在批量写入完成后调用。"""
    await self._lifecycle.finalize()

# lifecycle.py  
async def finalize(self) -> None:
    """遍历所有日期，生成缺失摘要/人格，执行摄入遗忘，保存。"""
```

### 1.3 遗忘路径整合

**文件：** `app/memory/memory_bank/lifecycle.py`, `app/memory/memory_bank/forget.py`

**现状：** `_post_write_forget_and_summarize` 中同时调用 `purge_forgotten()`（搜索型软标记→硬删）
+ `_forget_at_ingestion()`（摄入型硬删）。两套 RNG，双重执行。

**改法：**

1. 搜索时增量遗忘（`purge_forgotten`）保留在 `store.search()` 中不动——此为长期运行服务所需。
2. 摄入后遗忘移至 `finalize()`，单次执行。
3. `compute_ingestion_forget_ids()` 使用 `ForgettingCurve.rng`（受 config.seed 控制），
   不再在 `rng=None` 时创建裸 `random.Random()`。需修改函数签名——接受可选 `rng` 参数，
   由 `MemoryLifecycle._forget_at_ingestion()` 传入 `self._forget.rng`。

```python
# forget.py
def compute_ingestion_forget_ids(
    metadata: list[dict],
    reference_date: str,
    config: MemoryBankConfig,
    rng: random.Random | None = None,  # 由 MemoryLifecycle._forget_at_ingestion 传入 self._forget.rng；None 仅测试用
) -> list[int]:
```

### 1.4 批量写入

**文件：** `app/memory/memory_bank/lifecycle.py`, `app/memory/memory_bank/store.py`

**现状：** 逐条 `write(event)` → 各自调用 `embedding_client.encode()`。批量摄入 N 条需 N 次 HTTP 往返。

**改法：** 新增 `write_batch(events: list[MemoryEvent])`：

1. 收集所有 events 的 pair_texts（解析说话人、构建对话文本）
2. 一次 `embedding_client.encode_batch(pair_texts)` 调用
3. 逐条 `index.add_vector()`
4. 持久化索引（不触发摘要/遗忘）

**接口：**

```python
# store.py
async def write_batch(self, events: list[MemoryEvent]) -> list[str]:
    """批量写入，返回 faiss_id 列表。不触发摘要/遗忘。"""
    return await self._lifecycle.write_batch(events)
```

## B2：功能补全

### 2.1 update_feedback 实现

**文件：** `app/memory/memory_bank/store.py`, `app/memory/memory_bank/lifecycle.py`

**现状：** `store.py:239` 仅 `logger.debug()`。用户反馈不产生任何效果。

**改法：**

| action | 行为 | 理由 |
|--------|------|------|
| `accept` | `memory_strength += 2` | 主动确认权重高于被动回忆（+1） |
| `ignore` | `memory_strength = max(1, strength - 1)` | 削弱但不下探到 0（留修复余地） |
| 两者 | `last_recall_date` 更新为当天 | 接触即强化时间戳 |

实现路径：`store.update_feedback()` → `lifecycle.update_feedback(event_id, feedback)` →
按 faiss_id 查 metadata → 执行修改 → `_maybe_save()`。

### 2.2 EMBEDDING_MIN_SIMILARITY 生效

**文件：** `app/memory/memory_bank/retrieval.py`

**现状：** 配置项 `embedding_min_similarity=0.3` 存在但未被任何代码使用。

**改法：** `RetrievalPipeline.search()` 中 FAISS 搜索后、邻居合并前，过滤
`score < self._config.embedding_min_similarity` 的结果。

过滤在合并前执行——低分条目不配获得邻居扩展。

```python
# 在 FAISS search 之后、_merge_neighbors 之前
results = [r for r in results 
           if r.get("score", 0.0) >= self._config.embedding_min_similarity]
```

### 2.3 InteractionRecord 关联

**文件：** `app/memory/memory_bank/store.py`, `app/memory/memory_bank/lifecycle.py`

**现状：** `MemoryEvent.interaction_ids` 字段存在，无代码填充。`write_interaction()` 存入的
metadata 条目无反向引用。

**改法：** 轻量方案——`MemoryBankStore` 维护内存映射，不改 FAISS metadata schema。

```python
# store.py
self._interaction_map: dict[str, list[str]] = {}  # faiss_id → [interaction_faiss_id, ...]
```

- `write_interaction()` 写入后，将 interaction 的 faiss_id 追加到 metadata 中同 `source`（即同 date_key）的所有事件条目。此为有意设计——轻量方案下不作精确匹配，一个日期下所有 interaction 与所有事件互关联。`_interaction_map` 以事件 `faiss_id`（字符串）为键，值为该事件关联的 interaction faiss_id 列表。
- `get_history()` 返回时，从 `_interaction_map` 查表填充 `MemoryEvent.interaction_ids`。

缺陷：内存映射在服务重启后丢失。如需持久化，后续可改为存入 `extra_metadata` 或独立 JSON 文件。

## B3：架构优化

纯清理，不影响行为。

### 3.1 合并重复 _maybe_save

**文件：** `app/memory/memory_bank/store.py`

**现状：** `search()` 中两次 `_maybe_save()`——L131（purge 后）+ L147（strength 更新后）。

**改法：** 删除 L131 的调用。L147 处改为无条件 `_maybe_save()`（去掉 `if updated` 守卫），使 purge 修改不漏。

### 3.2 移除 chunk_size 缓存

**文件：** `app/memory/memory_bank/retrieval.py`

**现状：** `RetrievalPipeline` 携带 `_cached_*` 字段做首尾文本哈希快速路径。
中间条目变化时不失效（低概率 stale）。

**改法：** 删除缓存字段和 `_get_chunk_size()` 方法，直接调用模块级
`_get_effective_chunk_size(metadata, config)`。metadata 规模 10³ 量级，
排序开销可忽略。

删除内容：
- `self._cached_chunk_size`, `_cached_metadata_len`, `_cached_first_text`, `_cached_last_text`
- `_get_chunk_size()` 方法（用模块函数替代）

### 3.3 删除无效防御代码

**文件：** `app/memory/memory_bank/retrieval.py`

**现状：** `_gather_neighbor_indices` L262-263：

```python
if meta_idx not in neighbor_indices:
    neighbor_indices.insert(0, meta_idx)
```

`meta_idx` 在 L250 已加入，此分支永假。

**改法：** 删除 L262-263。

### 3.4 写入侧可观测性

**文件：** `app/memory/memory_bank/observability.py`, `app/memory/memory_bank/lifecycle.py`

**现状：** `MemoryBankMetrics` 只追踪 search + forget。

**改法：** 新增字段并纳入 `snapshot()`：

```python
write_count: int = 0
write_latency_ms: deque[float] = field(default_factory=lambda: deque(maxlen=1000))
embedding_latency_ms: deque[float] = field(default_factory=lambda: deque(maxlen=1000))
```

`write()` 和 `write_batch()` 执行时记录计数与延迟。

## B4：测试覆盖

不新增 benchmark 集成测试（属 VehicleMemBench 仓库）。聚焦单元级正确性。

### 4.1 摘要回归测试

**文件：** `tests/stores/test_summarizer.py`（已有，补充用例）

mock LLM 返回已知文本。验证：

| 场景 | 断言 |
|------|------|
| daily_summary 生成 | 返回文本含 `"The summary of the conversation on {date} is:"` 前缀 |
| overall_summary 幂等 | 第二次 `get_overall_summary()` 返回 `None` |
| daily_personality 存储 | `extra["daily_personalities"][date_key]` 有值 |
| overall_personality 聚合 | prompt 包含所有 daily_personality 文本 |
| LLM 返回空 | 触发 `SummarizationEmpty`，`extra["overall_summary"] = GENERATION_EMPTY` |

### 4.2 检索边界

**文件：** `tests/stores/test_retrieval.py`（已有，补充用例）

| 场景 | 断言 |
|------|------|
| 空索引 | `search()` 返回 `([], False)` |
| 全低于 similarity 阈值 | B2 过滤后返回空结果 |
| 说话人在 query 中 | 不涉及者 score ×0.75 |
| 无说话人在 query 中 | 无条目被降权 |
| corrupted 条目 | `store.search()` 跳过 `corrupted=True` 的结果 |
| 全遗忘 | `forgotten=True` 条目被 `RetrievalPipeline` 过滤 |

### 4.3 遗忘边界

**文件：** `tests/stores/test_forget.py`（已有，补充用例）

| 场景 | 断言 |
|------|------|
| 确定性模式 retention < 0.3 | `forgotten=True` |
| 概率模式同 seed 两次 | `maybe_forget()` 结果相同 |
| 节流 300s 内 | 二次调用返回 `None` |
| daily_summary 豁免 | `type=daily_summary` 条目不参与遗忘 |

## 不影响的范围

- FAISS 索引格式：不改（IndexIDMap(IndexFlatIP) + L2 归一化）
- retrieval.py 核心算法：不改（邻居合并、并查集去重、说话人降权逻辑）
- LLM prompt 内容：不改（已与 VMB 逐字对齐）
- `MemoryModule` / `MemoryStore` Protocol：不改接口签名
- GraphQL API 层：不改
- `store.py` 中 `format_search_results()`：不改

## 风险

| 风险 | 缓解 |
|------|------|
| 移除 write() 自动摘要后，interactive 使用场景摘要不触发 | `finalize_ingestion()` 提供显式触发点；长期运行服务可在定时任务中调用 |
| `_interaction_map` 内存映射重启丢失 | 标注为已知限制，后续可持久化到 JSON。当前不影响核心记忆功能 |
| 温度 0.7 使摘要更"随机" | VMB 使用的默认值。可通过环境变量覆盖 |
