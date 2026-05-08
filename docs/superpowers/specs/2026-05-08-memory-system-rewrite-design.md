# 记忆系统全面重写设计规格

## 背景

DrivePal 当前记忆系统从 VehicleMemBench (VMBench) MemoryBank 实验组移植而来。
移植过程中引入了 bug、缺失了多用户支持、且架构债务累积。
本规格描述全面重写方案，目标：修复已知 bug、支持多用户、清理架构债务。

## 模块结构

```
app/memory/
  __init__.py           # 导出
  interfaces.py         # MemoryStore Protocol（加 user_id）
  memory.py             # MemoryModule Facade + 工厂注册表
  schemas.py            # Pydantic 数据模型
  types.py              # MemoryMode 枚举
  singleton.py          # 线程安全单例
  components.py         # FeedbackManager
  embedding_client.py   # 异步 embedding，真批量 API 调用
  memory_bank/
    __init__.py          # 导出 MemoryBankStore
    store.py             # MemoryBankStore — 编排层
    faiss_index.py       # 多用户 FAISS 索引管理
    forget.py            # 统一遗忘模块
    llm.py               # LLM 薄封装
    retrieval.py         # 四阶段检索管道（纯函数）
    summarizer.py        # 摘要 + 人格生成
```

**删除清单：**
- `utils.py`（`cosine_similarity` 由 FAISS IP 替代，`compute_events_hash` 无调用方）
- `stores/__init__.py`（空壳，直接从 `memory_bank` 导出）
- `KeywordSearch` 类（无调用方）

**各模块职责：**

| 模块 | 做什么 | 不做什么 |
|------|--------|---------|
| `faiss_index.py` | 向量增删查、元数据 CRUD、磁盘持久化、per-user 隔离 | 遗忘/检索/摘要逻辑 |
| `retrieval.py` | 四阶段纯函数管道 | 不持有状态，不调持久化 |
| `forget.py` | 遗忘曲线计算，返回待删除 ID | 不直接操作索引 |
| `summarizer.py` | 日摘要/总摘要/日人格/总人格生成 | 不直接写索引 |
| `store.py` | 编排以上模块，实现 MemoryStore Protocol | 不含业务算法 |
| `llm.py` | 重试 + 上下文截断 | 不含 prompt 模板 |

## 多用户 FaissIndex

### 数据结构

```python
class FaissIndex:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._dim: int | None = None
        self._indices: dict[str, _UserIndex] = {}
        self._loaded: bool = False

@dataclass
class _UserIndex:
    index: faiss.IndexIDMap
    metadata: list[dict]
    next_id: int
    id_to_meta: dict[int, int]
    all_speakers: set[str]
    extra: dict
```

### 磁盘布局

```
{data_dir}/
  {user_id}/
    index.faiss
    metadata.json
    extra_metadata.json
```

单用户场景 `user_id` 默认 `"default"`。

### 关键方法

- `load()` — 扫描 data_dir 下所有子目录按 user_id 加载，损坏目录删除文件不预建索引
- `add_vector(user_id, text, embedding, timestamp, extra_meta)` — 向指定用户添加向量
- `search(user_id, query_emb, top_k)` — 检索指定用户
- `remove_vectors(user_id, faiss_ids)` — 移除指定用户向量
- `save(user_id)` — 持久化指定用户
- `get_metadata(user_id)` / `get_metadata_by_id(user_id, faiss_id)` / `get_extra(user_id)` / `get_all_speakers(user_id)` / `total(user_id)` — 只读访问器
- `reload(user_id)` — 重新加载指定用户索引（外部程序操作磁盘后调用）

### `_dim` 冲突处理

`_dim` 首次 `add_vector` 时锁定。后续用户维度不一致时抛 `ValueError`。

## 四阶段检索管道

全部纯函数，无类、无状态。

### 函数签名

```python
def merge_neighbors(results: list[dict], metadata: list[dict],
                    chunk_size: int) -> list[dict]:
    """阶段 2：同 source 连续条目合并，从外向内裁剪至 chunk_size。"""

def deduplicate_overlaps(results: list[dict]) -> list[dict]:
    """阶段 3：并查集去重，合并共享 index 的跨结果条目。"""

def apply_speaker_filter(results: list[dict], query: str,
                         all_speakers: list[str]) -> list[dict]:
    """阶段 4：说话人感知降权。"""

def update_memory_strengths(results: list[dict], metadata: list[dict],
                            reference_date: str | None) -> bool:
    """更新命中条目 memory_strength（+1）和 last_recall_date。返回是否有修改。"""

def get_effective_chunk_size(metadata: list[dict]) -> int:
    """P90 × 3 自适应 chunk size（环境变量 MEMORYBANK_CHUNK_SIZE 覆盖时跳过）。"""

def clean_search_result(result: dict) -> None:
    """移除内部字段，解码合并分隔符。"""
```

阶段 1（FAISS 粗排）在 `FaissIndex.search` 中完成。

### 说话人降权

```python
def _penalize_score(score: float) -> float:
    """向零方向移动 25%。"""
    return score * 0.75 if score >= 0 else score * 1.25
```

### 调用方式（store.py 中）

```python
raw = await self._index.search(user_id, query_emb, top_k * 4)
merged = merge_neighbors(raw, metadata, get_effective_chunk_size(metadata))
merged = deduplicate_overlaps(merged)
merged = apply_speaker_filter(merged, query, self._index.get_all_speakers(user_id))
merged.sort(key=lambda r: r["score"], reverse=True)
merged = merged[:top_k]
if update_memory_strengths(merged, metadata, self._reference_date):
    await self._index.save(user_id)
for r in merged:
    clean_search_result(r)
```

## 遗忘模块

仅两个纯函数，无类、无状态、无节流。

```python
def compute_forget_ids(
    metadata: list[dict],
    reference_date: str,
    *,
    mode: ForgetMode = ForgetMode.DETERMINISTIC,
    rng: random.Random | None = None,
    threshold: float = 0.15,
) -> list[int]:
    """遍历 metadata，返回应硬删除的 faiss_id 列表。
    跳过 daily_summary 类型。不修改传入的 metadata。"""

def compute_reference_date(metadata: list[dict]) -> str:
    """从 metadata 时间戳推算参考日期（最大日期 +1 天）。"""
```

### 调用点

- **摄入时**：`write_interaction` / `write` 末尾
- **检索时**：`search` 开头

两处调用同一函数，无软标记（`forgotten` 概念删除）。

### ForgetMode

```python
class ForgetMode(enum.Enum):
    DETERMINISTIC = "deterministic"  # retention < threshold → 删除
    PROBABILISTIC = "probabilistic"  # rng.random() > retention → 删除
```

## 摘要与人格生成

### 核心修复

`generate_daily_summary` 收集文本时调用 `_strip_source_prefix` 清理前缀。

### 方法签名

```python
class Summarizer:
    def __init__(self, llm: LlmClient, index: FaissIndex) -> None: ...

    async def generate_daily_summary(self, user_id: str, date_key: str) -> str | None:
        """为指定用户生成某天摘要。已存在返回 None。"""

    async def generate_overall_summary(self, user_id: str) -> str | None: ...
    async def generate_daily_personality(self, user_id: str, date_key: str) -> str | None: ...
    async def generate_overall_personality(self, user_id: str) -> str | None: ...
```

方法命名从 `get_*` 改为 `generate_*`（明确有副作用）。

### 职责边界

- `Summarizer` 只返回文本，不负责 embedding 入库
- `store.py` 调用 `Summarizer` 获取文本后，自行调 `embedding.encode` + `index.add_vector` 入库
- `_strip_source_prefix` 定义在 `retrieval.py` 并导出，`summarizer.py` 导入使用

## Embedding Client

### 真批量支持

```python
class EmbeddingClient:
    async def encode(self, text: str) -> list[float]:
        return (await self.encode_batch([text]))[0]

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """分批编码，每批一次 API 调用。"""
        results = []
        for i in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[i : i + self.BATCH_SIZE]
            results.extend(await self._encode_single_batch(batch))
        return results

    async def _encode_single_batch(self, texts: list[str]) -> list[list[float]]:
        """单批 API 调用，指数退避重试。"""
```

### EmbeddingModel 接口扩展

```python
class EmbeddingModel(Protocol):
    async def encode(self, text: str) -> list[float]: ...
    async def encode_batch(self, texts: list[str]) -> list[list[float]]: ...
```

具体实现类需实现 `encode_batch`。若未实现，`EmbeddingClient.encode_batch` 退化为逐条调用。

## MemoryStore Protocol

所有方法加 `user_id` 参数（默认 `"default"`）：

```python
class MemoryStore(Protocol):
    async def write(self, event: MemoryEvent, *, user_id: str = "default") -> str: ...
    async def search(self, query: str, top_k: int = 10, *, user_id: str = "default") -> list[SearchResult]: ...
    async def get_history(self, limit: int = 10, *, user_id: str = "default") -> list[MemoryEvent]: ...
    async def update_feedback(self, event_id: str, feedback: FeedbackData, *, user_id: str = "default") -> None: ...
    async def get_event_type(self, event_id: str, *, user_id: str = "default") -> str | None: ...
    async def write_interaction(self, query: str, response: str, event_type: str = "reminder",
                                *, user_id: str = "default", **kwargs: object) -> InteractionResult: ...
```

`MemoryModule` Facade 所有方法透传 `user_id`。

## Store 编排层

### write_interaction 流程

```
_ensure_loaded → 构造文本 → embedding.encode → index.add_vector
→ [遗忘] compute_forget_ids → index.remove_vectors → index.save
→ [后台] asyncio.create_task(background_summarize)
→ return InteractionResult
```

### search 流程

```
_ensure_loaded → [遗忘] compute_forget_ids → index.remove_vectors → index.save
→ embedding.encode(query) → index.search(粗排)
→ merge_neighbors → deduplicate_overlaps → apply_speaker_filter
→ 截断 top_k → update_memory_strengths → index.save
→ clean_search_result → 前置 overall_context → 返回 list[SearchResult]
```

### 加载策略

构造后调用 `_ensure_loaded()` 一次（布尔标记 `_loaded`），不再每次操作前重复加载。

## 测试

### 测试文件

```
tests/memory/
  test_faiss_index.py       # 多用户索引 CRUD
  test_retrieval.py         # 纯函数测试
  test_forget.py            # 纯函数测试
  test_summarizer.py        # mock LlmClient
  test_embedding_client.py  # mock EmbeddingModel
  test_store.py             # 集成测试，mock embedding + LLM，tmp_path
```

### P0 必须覆盖

- 多用户 add/search 隔离
- 损坏文件恢复
- 维度不匹配 ValueError
- 邻居合并 + chunk_size 裁剪
- 重叠去重（并查集）
- 说话人降权（正分 + 负分）
- 遗忘 deterministic/probabilistic 模式
- daily_summary 跳过遗忘

### P1 应覆盖

- write_interaction → search 端到端
- 后台摘要触发验证
- 多用户 write + search 互不干扰
- 遗忘启用时旧条目删除

### P2 锦上添花

- 摘要已存在返回 None
- 前缀清理验证
- Embedding 瞬态错误重试
- 退化模式（无 encode_batch）

### Mock 策略

- EmbeddingModel：固定随机向量（seed 确定）
- ChatModel：返回预设摘要文本
- FaissIndex：集成测试用真实 FAISS + tmp_path
- 时间：手动注入 reference_date

## 未解决问题

无。所有设计决策已确定。
