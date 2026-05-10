# 代码优化设计文档

2026-05-10

## 概述

基于全面代码审查 + VehicleMemBench 对照分析，修复 10 项代码层问题，分三组：

- **第一组（性能与配置）**：Fixes 1, 2, 3, 4, 10
- **第二组（检索增强）**：Fixes 5, 6, 7
- **第三组（小修）**：Fixes 8, 9

---

## 第一组：性能与配置优化

### Fix 1: Embedding 批量大小打通 config

**问题**：`EmbeddingModel.batch_encode()` 硬编码 `_BATCH_SIZE=32`，忽略 `MemoryBankConfig.embedding_batch_size=100`。

**修改文件**：
- `app/models/embedding.py`
- `app/memory/embedding_client.py`
- `app/memory/memory_bank/lifecycle.py`

**方案**：
1. `EmbeddingModel.__init__` 加 `batch_size: int = 32` 参数，存为 `self._batch_size`
2. `batch_encode()` 用 `self._batch_size` 替代模块级 `_BATCH_SIZE`
3. `get_cached_embedding_model()` 加可选 `embedding_batch_size` 参数
4. `EmbeddingClient.__init__` 加 `batch_size: int` 参数，透传给模型
5. `MemoryLifecycle` 构造时读取 `config.embedding_batch_size` 创建 `EmbeddingClient`

**不变**：默认值保持 32，向后兼容。MemoryBank 构造时显式传入 100。

---

### Fix 2: ChatModel 客户端复用

**问题**：`generate()`/`generate_stream()` 每请求 `async with self._create_client(provider) as client:`，创建/销毁 `AsyncOpenAI` 导致连接池丢失。

**修改文件**：`app/models/chat.py`

**方案**：
1. 模块级 `_client_cache: dict[str, openai.AsyncOpenAI]`，键 = `(base_url, api_key_hash)`
2. 模块级 `_client_cache_lock = asyncio.Lock()` 保护懒创建
3. 新增 `async def _get_cached_client(provider) -> AsyncOpenAI`
4. `generate()`/`generate_stream()` 中用 `await _get_cached_client(provider)` 替代 `self._create_client(provider)`，移除 `async with client`，仅保留 `async with sem:`
5. 新增 `async def close_client_cache()` 用于 lifespan 关闭
6. `clear_semaphore_cache()` 同步清理 `_client_cache`

**对 `_create_client`**：保留该方法作为回退创建逻辑，由 `_get_cached_client` 内部调用。

**缓存生命周期**：键由 `(base_url, api_key_hash)` 组成，provider 配置有限（通常 <10），无需驱逐策略。`close_client_cache()` 在 lifespan 关闭时清空所有缓存客户端。

---

### Fix 3: 消融实验环境变量移除热路径

**问题**：`workflow.py:342` 和 `rules.py:233` 每请求读 `os.getenv("ABLATION_DISABLE_*")`。

**修改文件**：
- `app/agents/workflow.py`
- `app/agents/rules.py`
- `experiments/ablation/ablation_runner.py`

**方案**：
1. `workflow.py`：模块级 `_ablation_disable_feedback = bool(int(os.getenv("ABLATION_DISABLE_FEEDBACK", "0")))`（仅模块加载时读一次），公开 `set_ablation_disable_feedback(v: bool)`
2. `rules.py`：同上模式，`_ablation_disable_rules` + `set_ablation_disable_rules(v: bool)`
3. `ablation_runner.py`：`AblationRunner.run_variant()` 中用 `set_ablation_disable_rules(True)` 替代 `os.environ[...]="1"`，移除 `ABLATION_DISABLE_RULES` 的 `_set_env`/`_restore_env` 逻辑

**向后兼容**：模块加载时仍从环境变量读取初始值，CLI 参数传 `ABLATION_DISABLE_RULES=1` 仍生效。

---

### Fix 4: memory_strength 上限

**问题**：`retrieval.py:238` 检索命中 `memory_strength += 1`，无上限。高频查询驱动无限增长，遗忘曲线失效。

**修改文件**：
- `app/memory/memory_bank/config.py`
- `app/memory/memory_bank/retrieval.py`

**方案**：
1. `MemoryBankConfig` 加 `max_memory_strength: int = 10`（环境变量 `MEMORYBANK_MAX_MEMORY_STRENGTH`）
2. `_update_memory_strengths()` 中 `new_strength = min(existing + 1.0, config.max_memory_strength)`
3. 更新 `retrieval.py:218` 注释：移除"不再设上限"的描述

**对齐**：原始 MemoryBank 论文使用 `cap=10`。

---

### Fix 10: fatigue_threshold 模块级缓存

**问题**：`_get_fatigue_threshold()` 每规则条件求值时重读 `os.environ` + 校验。

**修改文件**：`app/agents/rules.py`

**方案**：
1. 模块级 `_cached_fatigue_threshold: float | None = None`
2. `_get_fatigue_threshold()` 先查缓存，未命中才读 env 并缓存
3. 公开 `reset_fatigue_threshold_cache()` 供测试环境

---

## 第二组：检索增强

### Fix 5: 检索加权公式（论文公式 3-2）

**问题**：检索管道仅用 FAISS 内积 + 说话人降权，不含 `Score = α·Sim + (1-α)·R` 加权。

**修改文件**：
- `app/memory/memory_bank/config.py`
- `app/memory/memory_bank/retrieval.py`

**方案**：
1. `MemoryBankConfig` 加 `retrieval_alpha: float = 0.7`（`MEMORYBANK_RETRIEVAL_ALPHA`）
2. 在 `RetrievalPipeline.search()` 中，`_apply_speaker_filter()` 之后、最终 `[:top_k]` 截断之前，插入新步骤 `_apply_retention_weighting(results, metadata, reference_date, alpha)`
3. 对每条结果：
   - 从 metadata 取 `memory_strength` 和 `last_recall_date`
   - 计算 `days = (ref_date - last_recall).days`，若无 `last_recall_date` 用 `days=0`
   - 计算 `retention = e^(-days / max(strength, 0.001))`
   - 计算 `adjusted = α × max(score, 0.0) + (1-α) × retention`
4. 按 `adjusted` 重排序，截断 top_k

**插入位置理由**：说话人匹配是硬约束（降权 25%），应在语义+遗忘加权之前完成。`max(score, 0.0)` 截断防止 FAISS 负分稀释权重。

---

### Fix 6: BM25 关键词回退

**问题**：FAISS 最高相似度 <0.5 时无回退机制。

**修改文件**：
- `pyproject.toml`（加依赖）
- `app/memory/memory_bank/config.py`
- `app/memory/memory_bank/retrieval.py`

**方案**：
1. 加 `rank-bm25` 依赖（纯 Python，约 50KB）
2. `MemoryBankConfig` 加：
   - `bm25_fallback_enabled: bool = True`（`MEMORYBANK_BM25_FALLBACK_ENABLED`）
   - `bm25_fallback_threshold: float = 0.5`（`MEMORYBANK_BM25_FALLBACK_THRESHOLD`）
3. `RetrievalPipeline` 维持 `_bm25_corpus: list[str]` 和 `_bm25_index: BM25Okapi | None`
4. 新增方法 `_rebuild_bm25_index()`，从 metadata 提取全部 text 作为语料
5. `search()` 中：FAISS 粗排后，若最高分 < `bm25_fallback_threshold` 且启用：
   a. 若 `_bm25_index` 为 None 或 stale，重建
   b. BM25 tokenize query + 评分全部文档
   c. 取 top_k BM25 结果，与 FAISS 结果合并去重
   d. 合并后的结果走后续阶段（邻居合并、说话人降权、保留率加权）
6. `put_vectors()` 后标记 BM25 索引失效

**触发频率说明**：车载场景的短查询+领域术语下，密集检索（FAISS）通常表现良好，BM25 回退极少触发（预期 <5% 请求）。该机制的收益主要在边界场景（如查询含罕见拼写、缩写），成本是索引维护开销。若后续测试发现触发率 <1%，可考虑将 `bm25_fallback_enabled` 默认改为 `False`。

---

### Fix 7: FAISS 索引类型可配置

**问题**：论文草稿写 IVF_FLAT，代码用 IndexFlatIP。代码选择正确，为未来扩展预留接口。

**修改文件**：
- `app/memory/memory_bank/config.py`
- `app/memory/memory_bank/index.py`

**方案**：
1. `MemoryBankConfig` 加：
   - `index_type: Literal["flat", "ivf_flat"] = "flat"`（`MEMORYBANK_INDEX_TYPE`）
   - `ivf_nlist: int = 128`（`MEMORYBANK_IVF_NLIST`）
2. `FaissIndex.__init__` 中接收 `index_type` 和 `ivf_nlist`
3. `_build_index()` 根据 `index_type` 选择构建逻辑：
   - `"flat"`：`IndexIDMap(IndexFlatIP(dim))`（默认，精确检索）
   - `"ivf_flat"`：`IndexIDMap(IndexIVFFlat(quantizer, dim, nlist))`（需训练）
4. IVF 模式时，`add_vectors()` 之后调用 `index.train(vectors)`，若向量数 < nlist 则回退 flat
5. `index.py` 顶部文档字符串加说明：Flat 适用于 <100K 向量，提供精确结果；IVF 适用于大规模向量，有精度损失

**实现范围控制**：此 Fix 为轻量预留——只需 config 字段 + `if index_type == "ivf_flat"` 骨架，不须完整 IVF 训练+推理路径。`"flat"` 是唯一完整工作的模式。

---

## 第三组：小修

### Fix 8: _source_event_index 磁盘缓存

**问题**：`store.py` 中 `_source_event_index` 纯内存，重启后全量 metadata 扫描回退。

**修改文件**：`app/memory/memory_bank/store.py`

**方案**：
1. `_ensure_loaded()` 中加载 `memorybank/source_event_index.json`（若存在）
2. 新增 `_source_index_dirty = False` 标记
3. `write()` / `write_batch()` 修改后置 `_source_index_dirty = True`
4. `_maybe_save()` 中同步写入 JSON（格式：`{"date_key": ["faiss_id", ...]}`）
5. `close()` 中强制写入

**损坏恢复**：若 JSON 文件格式损坏或 `faiss_id` 与当前索引不匹配，回退到现有行为——标记 dirty，下一次 `write_interaction()` 触发 metadata 全量扫描重建。

---

### Fix 9: exportData 遍历优化

**问题**：`mutation.py` 用 `rglob("*")` 遍历全目录（含 memorybank 二进制文件），再循环内跳过。

**修改文件**：`app/api/resolvers/mutation.py`

**方案**：
1. 改为按后缀分别 `rglob`，天然排除无匹配后缀的文件（如 `index.faiss`）：
   ```python
   allowed_suffixes = {".jsonl", ".toml", ".json"}
   for suffix in allowed_suffixes:
       for fpath in u_dir.rglob(f"*{suffix}"):
           if "memorybank" in fpath.parts:
               continue
           ...
   ```
2. 二进制大文件（`index.faiss`）无匹配后缀，`rglob` 不会返回它们

---

## 影响范围汇总

| 文件 | 修改的 Fixes |
|------|-------------|
| `app/models/embedding.py` | 1 |
| `app/models/chat.py` | 2 |
| `app/memory/embedding_client.py` | 1 |
| `app/memory/memory_bank/config.py` | 4, 5, 6, 7 |
| `app/memory/memory_bank/retrieval.py` | 4, 5, 6 |
| `app/memory/memory_bank/index.py` | 7 |
| `app/memory/memory_bank/lifecycle.py` | 1 |
| `app/memory/memory_bank/store.py` | 8 |
| `app/agents/workflow.py` | 3 |
| `app/agents/rules.py` | 3, 10 |
| `app/api/resolvers/mutation.py` | 9 |
| `experiments/ablation/ablation_runner.py` | 3 |
| `pyproject.toml` | 6 |

共 13 个文件。修复均向后兼容，不改变 API 契约。

---

## 测试计划

- 现有 292 测试全部通过（基线已验证）
- Fix 1：验证 EmbeddingModel batch_size 参数传递
- Fix 2：验证客户端缓存复用（同 base_url 两次调用共享 client）
- Fix 3：验证模块级变量替代 env 读取生效
- Fix 4：验证 strength 不超过 max_memory_strength
- Fix 5：验证保留率加权后排序变化（mock 数据）
- Fix 6：验证 BM25 回退触发条件
- Fix 7：验证 index_type 选择逻辑
- Fix 8：验证 JSON 序列化/反序列化
- Fix 9：验证 memorybank 目录下的文件不出现
- Fix 10：验证阈值缓存命中
