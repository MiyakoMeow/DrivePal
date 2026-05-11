# 记忆系统

`app/memory/` —— MemoryBank 记忆系统及基础设施。

## MemoryBank 记忆系统

`app/memory/memory_bank/`。基于论文 MemoryBank 实现。

### 文件结构

```
app/memory/memory_bank/
├── config.py         # 集中配置（pydantic-settings，MEMORYBANK_ 前缀）
├── index.py          # FAISS 索引管理（IndexIDMap(IndexFlatIP) + LoadResult降级恢复）
├── index_reader.py   # IndexReader Protocol（只读视图）
├── retrieval.py      # 四阶段检索管道
├── forget.py         # Ebbinghaus 遗忘曲线
├── summarizer.py     # 分层摘要 + 人格生成
├── llm.py            # LLM 封装（上下文截断重试，异常化）
├── lifecycle.py      # 写入/遗忘/摘要编排（批量嵌入编码）
├── store.py          # MemoryBankStore Facade（MemoryStore Protocol 实现）
├── observability.py  # 可观测性指标（MemoryBankMetrics）
└── bg_tasks.py       # 后台任务管理器
```

### 架构

三层：Interaction（原始交互）→ Event（语义摘要）→ Summary（层级摘要）

### 记忆数据模型

`app/memory/schemas.py`。核心类型：

| 类型 | 关键字段 | 说明 |
|------|----------|------|
| `MemoryEvent` | id, content, type, memory_strength, last_recall_date, interaction_ids, speaker | 语义摘要后的事件（agent 输出） |
| `InteractionRecord` | id, event_id, query, response, timestamp, memory_strength | 原始用户↔系统交互 |
| `FeedbackData` | event_id, action(accept\|ignore), modified_content | 用户反馈，action 校验 `InvalidActionError` |
| `SearchResult` | event(dict), score(float), interactions(list[dict]) | 检索结果包装，`to_public()` 清洗内部评分字段（store 返回前调用） |
| `InteractionResult` | event_id, interaction_id | 写入结果 |

MemoryEvent 通过 `interaction_ids` 列表关联交互，检索命中时自动展开。

### FAISS索引

- IndexIDMap(IndexFlatIP) + L2归一化（等价余弦相似度）
- 自适应分块（P90×3 动态校准 chunk_size）
- `save()` 持有 asyncio.Lock 防止并发写入损坏
- 关键阈值：`EMBEDDING_MIN_SIMILARITY=0.3`

### 索引损坏恢复

`FaissIndex.load()` 返回 `LoadResult(ok, warnings, recovery_actions)`。三级降级策略：

| 损坏类型 | 恢复策略 |
|----------|----------|
| `metadata.json` 格式错 | 从 FAISS `id_map` 提取实际标签重建骨架（标记 `corrupted=True`） |
| `extra_metadata.json` 损坏 | 忽略，空 dict 启动（下次摘要自动重建） |
| Count mismatch | 以 index 为权威——从 `id_map` 补缺失骨架条目 |
| `index.faiss` 读失败 | 备份 `.bak` 后重建空索引 |

### 四阶段检索管道

1. query embedding + FAISS 粗排（top_k × 4）
2. 邻居合并（同 source 连续条目）
3. 重叠去重（并查集）
4. 说话人感知降权（查询含说话人名的无关条目降权 ×0.75）

### 遗忘曲线

`retention = e^(-days / strength)`

- **默认确定性模式**：retention < `SOFT_FORGET_THRESHOLD=0.3` 标记遗忘（memory_strength=0, forgotten=True）
- **可选概率性模式**：`MEMORYBANK_FORGET_MODE=probabilistic`，每条目独立掷骰子
- **回忆强化**：检索命中 memory_strength += 1（上限 max_memory_strength，默认 10）
- **节流**：`FORGET_INTERVAL_SECONDS=300`，两次遗忘判断至少间隔5分钟
- **搜索评分**：FAISS 内积 + 说话人感知降权（×0.75/×1.25）

### 摘要与人格

- **每日摘要**：每次写入后异步后台生成（不阻塞主流程）
- **总体摘要**：有 daily_summary 即生成；已存在则跳过（不可变保护）
- **每日人格**：同上，按日期生成后不覆盖
- **总体人格**：基于每日人格汇总生成；已存在则跳过

### 后台任务管理器

`app/memory/memory_bank/bg_tasks.py`

- asyncio 任务注册与调度（`create_task` + 跟踪集）
- `close()` 方法：等待所有 inflight 任务完成，支持优雅关闭
- 摘要生成等异步后处理通过此模块调度，不阻塞写入主流程

### 聚合

- 字符重叠 ≥ 45% 或余弦相似度 ≥ 0.8 聚合为同一事件
- 聚合后用LLM重新摘要事件 content
- 检索命中事件时自动展开关联交互

### 与原始论文差异

- 硬删除 → 软标记（可恢复）
- 启动时批量遗忘 → 每次搜索末尾渐进式遗忘
- 无级联删除 summary → 保留所有 summary 更安全

## 记忆模块基础设施

### MemoryModule 单例

`app/memory/singleton.py`

- 线程安全双检锁模式（`threading.Lock`）
- `get_memory_module()` 懒初始化：`MemoryModule(data_dir, embedding_model, chat_model)`
- API resolvers 通过此入口获取全局唯一 MemoryModule 实例

### 多用户隔离

`MemoryModule.get_store(user_id)` 返回 per-user `MemoryBankStore` 实例。每用户独立子目录 `data/users/{user_id}/`（含 memorybank/ 子目录及独立 JSONL/TOML 文件），由 `config.user_data_dir(user_id)` 生成路径。下游组件（RetrievalPipeline、MemoryLifecycle、Summarizer）构造时绑定用户目录，无需 `user_id` 参数。

### 可观测性

`app/memory/memory_bank/observability.py` 提供 `MemoryBankMetrics`（dataclass，零锁开销）。指标：search_count、search_latency_ms（P50/P90）、forget_count、background_task_failures 等。`MemoryBankStore.metrics` 属性获取实例 → `MemoryModule.get_metrics(user_id)` 聚合查询。

### EmbeddingClient 维度检测

`app/memory/embedding_client.py`

- `EmbeddingModel` 的薄代理
- `encode_batch()` 含双重校验：
  - 数量匹配：输入数 ≠ 输出数 → `RuntimeError`
  - 维度一致性：所有向量维度不同 → `RuntimeError`
- 重试由 `EmbeddingModel` 内部处理（3 次指数退避），此层不再重复

## 隐私保护

`app/memory/privacy.py`。

### 位置脱敏

写入记忆前自动脱敏位置信息：
- 经纬度截断至小数点后 2 位（约 1km 精度）
- 地址只保留街道级（逗号前第一段）
- `sanitize_context()` 递归处理 `spatial.current_location` + `destination`

### 数据可携带性

`exportData(currentUser)` mutation 导出当前用户全量文本文件（JSONL/TOML/JSON），返回 `{files: {filename: content}}`。`deleteAllData(currentUser)` 删除 `data/users/{currentUser}/` 整个目录。
