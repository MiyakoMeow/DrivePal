# app/memory - 记忆系统

基于 MemoryBank 论文的三层架构：Interaction（原始交互）→ Event（语义摘要）→ Summary（层级摘要）。

## 模块结构

```
memory/
├── __init__.py         # 包初始化
├── memory.py           # MemoryModule Facade + 工厂注册表 + per-user store 注册表
├── interfaces.py       # MemoryStore Protocol（含 close()）
├── types.py            # MemoryMode 枚举
├── schemas.py          # 数据模型
├── singleton.py        # 线程安全单例（双检锁）
├── privacy.py          # 隐私保护（位置脱敏）
├── embedding_client.py # Embedding 薄代理（维度一致性检测）
├── exceptions.py       # 异常体系
├── utils.py            # 余弦相似度 + 事件hash
├── stores/             # stores 命名空间（含 __init__.py）
└── memory_bank/        # MemoryBank 后端实现
    ├── __init__.py
    ├── config.py       # 集中配置（pydantic-settings，MEMORYBANK_ 前缀）
    ├── index.py        # FAISS 索引管理
    ├── index_reader.py # IndexReader Protocol（只读视图）
    ├── retrieval.py    # 四阶段检索管道
    ├── forget.py       # Ebbinghaus 遗忘曲线
    ├── summarizer.py   # 分层摘要 + 人格生成
    ├── llm.py          # LLM 封装（上下文截断重试）
    ├── lifecycle.py    # 写入/遗忘/摘要编排
    ├── store.py        # MemoryBankStore Facade
    ├── observability.py# 可观测性指标
    └── bg_tasks.py     # 后台任务管理器
```

## 核心数据模型（schemas.py）

| 类型 | 关键字段 | 说明 |
|------|----------|------|
| `MemoryEvent` | id, created_at, content, type, description, memory_strength, last_recall_date, date_group, interaction_ids, updated_at, speaker | 语义摘要后的事件 |
| `InteractionRecord` | id, event_id, query, response, timestamp, memory_strength, last_recall_date | 原始用户↔系统交互 |
| `FeedbackData` | event_id, action(accept\|ignore), type, timestamp, modified_content | 用户反馈 |
| `SearchResult` | event(dict), score(float), source(str), interactions(list[dict]) | 检索结果包装 |
| `InteractionResult` | event_id, interaction_id | 写入结果 |
| `InvalidActionError` | — | action 值非 accept/ignore 时抛出的异常（继承 ValueError） |

MemoryEvent 通过 `interaction_ids` 列表关联交互，检索命中时自动展开。

## MemoryModule（memory.py + singleton.py）

- 线程安全双检锁模式（`threading.Lock`），`get_memory_module()` 懒初始化
- 公开 Facade 方法：`write()` / `write_interaction()` / `search()` / `get_history()` / `get_event_type()` / `update_feedback()` / `close()`。内部通过 `_get_store()` 路由至 per-user 实例。
- 每用户独立子目录 `data/users/{user_id}/`，下游组件构造时绑定用户目录

## MemoryStore Protocol（interfaces.py）

定义存储层契约接口（含 `close()` 方法），MemoryBankStore 实现该 Protocol。

## MemoryBank 后端（memory_bank/）

### FAISS 索引（index.py）

- IndexIDMap(IndexFlatIP) + L2归一化（等价余弦相似度）
- `save()` 持有 asyncio.Lock 防止并发写入损坏
- 自适应分块（P90×3 动态校准 chunk_size）实现在 retrieval.py

### 索引损坏恢复

`FaissIndex.load()` 返回 `LoadResult(ok, warnings, recovery_actions)`。三级降级：

| 损坏类型 | 恢复策略 |
|----------|----------|
| `metadata.json` 格式错 | 从 FAISS `id_map` 提取实际标签重建骨架（标记 `corrupted=True`） |
| `extra_metadata.json` 损坏 | 忽略，空 dict 启动（下次摘要自动重建） |
| Count mismatch | 以 index 为权威——从 `id_map` 补缺失骨架条目 |
| `index.faiss` 读失败 | 备份 `.bak` 后重建空索引 |

### 四阶段检索管道（retrieval.py）

1. query embedding + FAISS 粗排（top_k × 4）
2. 邻居合并（同 source 连续条目）
3. 重叠去重（并查集，基于 `_merged_indices` 共享引用去重）
4. 说话人感知降权（查询含说话人名的无关条目降权 ×0.75）

### 遗忘曲线（forget.py）

`retention = e^(-days / (time_scale × strength))`

- **确定性模式**（默认）：retention < 0.3 标记遗忘
- **概率性模式**：`MEMORYBANK_FORGET_MODE=probabilistic`，每条目独立掷骰
- **回忆强化**：检索命中 memory_strength += 1（上限 `max_memory_strength`，默认 10）
- **节流**：`FORGET_INTERVAL_SECONDS=300`
- 环境变量 `MEMORYBANK_ENABLE_FORGETTING`（默认关闭）

### 摘要与人格（summarizer.py）

- 每日摘要/人格：`lifecycle.finalize()` 中同步生成（串行遍历日期，不阻塞主流程前序写入），已存在则跳过
- 总体摘要/人格：基于每日数据汇总，不可变（已存在则跳过）
- LLM 调用默认 temperature=0.3, max_tokens=400

### 后台任务管理器（bg_tasks.py）

- asyncio 任务注册与调度（`create_task` + 跟踪集）
- `close()`：等待所有 inflight 任务完成
- 当前仅备后调用（摘要生成不经此模块，由 lifecycle.finalize() 同步执行）

### 可观测性（observability.py）

`MemoryBankMetrics`（dataclass，零锁开销）：search_count、search_latency_ms（P50/P90）、forget_count、background_task_failures 等。

### 与原始论文差异

- 硬删除 → 软标记（可恢复）
- 启动时批量遗忘 → 每次搜索末尾渐进式遗忘
- 无级联删除 summary → 保留所有 summary

## EmbeddingClient（embedding_client.py）

- `EmbeddingModel` 的薄代理
- `encode_batch()` 双重校验：数量匹配 + 维度一致性（不一致 → `RuntimeError`）
- 重试由 `EmbeddingModel` 内部处理（3 次指数退避）

## 隐私保护（privacy.py）

- 经纬度截断至小数点后 2 位（约 1km 精度）
- 地址只保留街道级（逗号前第一段）
- `sanitize_context()` 递归处理 `spatial.current_location` + `destination`

## 数据可携带性

- `exportData()` mutation 导出用户全量文本文件
- `deleteAllData()` 删除用户整个目录
