# MemoryBank 深度重构设计

## 背景

DrivePal 记忆系统从 VehicleMemBench `memorybank.py` 移植而来，当前存在以下问题：

1. **单用户限制**：所有方法无 `user_id` 参数，无法支持多乘员车载场景
2. **Facade 层 YAGNI**：`MemoryModule` + `MemoryMode` 枚举 + 工厂注册表仅服务于 `MemoryBankStore` 一种实现
3. **正确性缺陷**：
   - `write` 中每条消息单独 `encode()`，N 条产生 N 次 API 调用
   - 遗忘双路径（`_purge_forgotten` 软标记 + `_forget_at_ingestion` 硬删除）语义重叠
   - `_background_summarize` 中 extra 与向量非原子持久化
   - `FaissIndex.get_metadata()` 返回可变引用，外部可随意 mutate
4. **功能缺失**：无参考日期自动计算，遗忘行为在长间隔使用时不可预测

## 目标

- 多用户支持（per-user FAISS 索引、metadata、extra）
- 删除无用 Facade/工厂/枚举层
- 批量嵌入
- 遗忘路径统一
- metadata 可变性管控
- 参考日期自动计算
- 接口不兼容重构，优先正确性和功能完善

## 不做的事

- 不保留 Facade/工厂/Protocol 多实现可替换性
- 不实现 VMB 的 benchmark 集成函数（`run_add`/`format_search_results` 等）
- 不增加 LLM 调参接口（temperature/top_p 等由 ChatModel 配置决定）

---

## 文件布局

### 最终结构

```
app/memory/
  __init__.py              # 导出 MemoryBankStore + schemas
  interfaces.py            # MemoryStore Protocol（多用户版）
  schemas.py               # 不变
  utils.py                 # 保留
  singleton.py             # 简化，直接 MemoryBankStore 单例
  embedding_client.py      # 不变
  memory_bank/
    __init__.py             # 导出 MemoryBankStore
    store.py                # MemoryBankStore（多用户版）
    faiss_index.py          # FaissIndexManager + _UserIndex
    retrieval.py            # RetrievalPipeline（多用户版）
    llm.py                  # 不变
    summarizer.py           # Summarizer（多用户版）
    forget.py               # compute_ingestion_forget_ids 保留，删除 ForgettingCurve 类
```

### 删除的文件

| 文件 | 原因 |
|------|------|
| `app/memory/memory.py` | Facade 层无第二种实现 |
| `app/memory/types.py` | `MemoryMode` 枚举仅 1 值 |
| `app/memory/stores/__init__.py` | 整个 stores/ 目录删除 |

---

## 模块设计

### 1. FaissIndexManager

替代现有 `FaissIndex`，管理多用户索引。

#### 内部数据结构

```python
@dataclass
class _UserIndex:
    index: faiss.IndexIDMap
    metadata: list[dict]
    next_id: int
    id_to_meta: dict[int, int]
    speakers: set[str]
```

#### 存储路径

```
data_dir/
  user_{user_id}/
    index.faiss
    metadata.json
    extra_metadata.json
```

#### 方法

| 方法 | 签名 | 说明 |
|------|------|------|
| `load` | `async (user_id: str) -> None` | 延迟加载；已加载则跳过（文件 I/O） |
| `save` | `async (user_id: str) -> None` | 持久化索引 + metadata + extra（文件 I/O） |
| `add_vector` | `async (user_id, text, emb, ts, extra_meta?) -> int` | 添加向量，返回 faiss_id（自动 load） |
| `search` | `async (user_id, query_emb, top_k) -> list[dict]` | 检索，结果每项含 `_meta_idx`/`text`/`score`/`timestamp`/`memory_strength`/`speakers` |
| `remove_vectors` | `async (user_id, faiss_ids: list[int]) -> None` | 删除向量并同步 next_id/id_to_meta/speakers（next_id 保持单调递增，不复用已删除 ID） |
| `get_metadata` | `(user_id) -> list[dict]` | 返回 **deep copy** |
| `update_metadata` | `async (user_id, faiss_id, updates: dict) -> None` | 显式更新单条 |
| `batch_update_metadata` | `async (user_id, updates: dict[int, dict]) -> None` | 批量更新 {meta_idx: updates} |
| `get_metadata_by_id` | `(user_id, faiss_id) -> dict \| None` | O(1) 查找 |
| `get_extra` | `(user_id) -> dict` | 获取 extra_metadata 的**可变引用**（与 get_metadata deep copy 不同；调用方可原地修改，由 store/save 持久化） |
| `total` | `async (user_id) -> int` | 索引向量数 |
| `is_loaded` | `(user_id) -> bool` | 是否已加载 |
| `get_all_speakers` | `(user_id) -> list[str]` | 已知说话人列表 |
| `parse_speaker_line` | `(line: str) -> tuple[str \| None, str]`（@staticmethod） | 按首个 `": "` 分割说话人与内容 |

#### 校验

加载时：
1. `_validate_metadata_structure`：list[dict]，每个含 `faiss_id`（int，无重复）
2. `_validate_index_count`：`index.ntotal == len(metadata)`
3. 损坏时删除 index.faiss / metadata.json / extra_metadata.json，返回空索引

#### 不变式

- `get_metadata()` 返回 deep copy，外部修改不影响内部状态
- 所有 metadata 变更通过 `update_metadata` / `batch_update_metadata`
- `add_vector` 增量更新 speakers 缓存
- `remove_vectors` 重建 speakers 缓存 + 同步 next_id

> **关于 Protocol 的角色：** 此处 Protocol 仅用于**类型检查**（静态 Duck Typing），确保 MemoryBankStore 满足接口契约。非运行时多态——当前无第二种实现，"不做的事"中已声明不保留 Facade/工厂层。Protocol 的存在只为 IDE 提示和 type checker 验证，不引入运行时抽象开销。

### 2. MemoryStore Protocol

```python
class MemoryStore(Protocol):
    store_name: str
    requires_embedding: bool
    requires_chat: bool

    async def write(self, user_id: str, event: MemoryEvent) -> str: ...
    async def write_interaction(
        self,
        user_id: str,
        query: str,
        response: str,
        event_type: str = "reminder",
        *,
        user_name: str = "User",
        ai_name: str = "AI",
    ) -> InteractionResult: ...
    async def search(
        self, user_id: str, query: str, top_k: int = 5,
    ) -> list[SearchResult]: ...
    async def get_history(
        self, user_id: str, limit: int = 10,
    ) -> list[MemoryEvent]: ...
    async def get_event_type(
        self, user_id: str, event_id: str,
    ) -> str | None: ...
    async def update_feedback(
        self, user_id: str, event_id: str, feedback: FeedbackData,
    ) -> None: ...
```

变化：
- 所有方法加 `user_id: str` 第一参数
- `write_interaction` 去掉 `**kwargs`，改为显式 `user_name`/`ai_name` 关键字参数
- 删除 `supports_interaction` 属性

### 3. MemoryBankStore

#### 构造函数

```python
def __init__(
    self,
    data_dir: Path,
    embedding_model: EmbeddingModel,  # 必需，不再可选
    chat_model: ChatModel,            # 必需，不再可选
    seed: int | None = None,
    reference_date: str | None = None,
) -> None
```

embedding 和 chat 是硬依赖，不再接受 None。

**类型映射：** 构造器参数 `EmbeddingModel`/`ChatModel` 为纯数据类型（来自 `app/models/types.py`），内部通过 `EmbeddingClient(embedding_model)` / `LlmClient(chat_model, rng=rng)` 封装。转换在构造函数内联完成，不依赖工厂。

#### 内部组件

| 组件 | 类型 | 说明 |
|------|------|------|
| `_index_manager` | `FaissIndexManager` | 多用户索引管理 |
| `_embedding_client` | `EmbeddingClient` | 嵌入代理 |
| `_rng` | `random.Random` | 随机数（seed 可复现） |
| `_seed_provided` | `bool` | 是否提供了 seed |
| `_reference_date` | `str | None` | 遗忘参考日期 |
| `_llm` | `LlmClient` | LLM 调用 |
| `_retrieval` | `RetrievalPipeline` | 检索管道 |
| `_summarizer` | `Summarizer` | 摘要/人格生成 |
| `_forgetting_enabled` | `bool` | 遗忘开关 |

#### 参考日期解析

```python
def _get_reference_date(self, user_id: str) -> str | None:
    """优先构造器 reference_date，未设置则从 metadata 最新 timestamp +1 天推导。"""
    if self._reference_date:
        return self._reference_date
    metadata = self._index_manager.get_metadata(user_id)
    if not metadata:
        return None
    timestamps = [m.get("timestamp", "")[:10] for m in metadata if m.get("timestamp")]
    if not timestamps:
        return None
    max_ts = max(timestamps)
    ref = date.fromisoformat(max_ts) + timedelta(days=1)
    return ref.strftime("%Y-%m-%d")
```

#### write(user_id, event)

> `parse_speaker_line` 为 `FaissIndexManager` 的 `@staticmethod`（见 §1），签名：`(line: str) -> tuple[str | None, str]`，按首个 `": "` 分割说话人与内容。

1. `await _index_manager.load(user_id)`
2. 解析 `event.content` 按 `\n` 分行 → 逐行 `parse_speaker_line` 判断是否为说 话人行
3. 有说话人行时：按行顺序交替配对（偶数行为说话人，奇数行为内容），奇数行不足时丢弃末尾说话人行
4. 无说话人行时：用 `event.speaker` 或 "System" 作为单条，整段 content 为其内容
5. **批量嵌入**：`await self._embedding_client.encode_batch(all_texts)`
6. 逐条 `await _index_manager.add_vector(user_id, ...)`
7. 遗忘：`await _forget_at_ingestion(user_id)`
8. `await _index_manager.save(user_id)`
9. 后台摘要：`date_key = event.timestamp[:10]`（取 YYYY-MM-DD）；`asyncio.create_task(_background_summarize(user_id, date_key))`

#### write_interaction(user_id, query, response, ...)

1. `await _index_manager.load(user_id)`
2. 格式化为 `Conversation content on {date}:[|{user_name}|]: {query}; [|{ai_name}|]: {response}`
3. `await self._embedding_client.encode(text)` （单条，无需批量）
4. `await _index_manager.add_vector(user_id, ...)`
5. 遗忘 + save + 后台摘要（同 write）

#### search(user_id, query, top_k)

1. `await _index_manager.load(user_id)`
2. 检查 total == 0 则返回 []
3. `await _retrieval.search(user_id, query, top_k, reference_date)`
4. 从 `_index_manager.get_extra(user_id)` 取 overall_summary / overall_personality
5. 构造前置 `SearchResult`（score=inf）：`SearchResult(content=overall_summary or overall_personality, score=float('inf'), event_type="overall_context", timestamp="", memory_strength=0, speakers=[])`
6. 遍历 retrieval 结果 `dict` 列表，每项构造 `SearchResult(content=m["text"], score=m["score"], event_type=m.get("event_type", "reminder"), timestamp=m.get("timestamp", ""), memory_strength=m.get("memory_strength", 1), speakers=m.get("speakers", []))`
7. 返回

#### _forget_at_ingestion(user_id)

```python
async def _forget_at_ingestion(self, user_id: str) -> None:
    if not self._forgetting_enabled:
        return
    ref_date = self._get_reference_date(user_id)
    if not ref_date:
        return
    metadata = self._index_manager.get_metadata(user_id)
    ids = compute_ingestion_forget_ids(
        metadata, ref_date,
        rng=self._rng,
        mode=ForgetMode.PROBABILISTIC if self._seed_provided else ForgetMode.DETERMINISTIC,
    )
    if ids:
        await self._index_manager.remove_vectors(user_id, ids)
```

#### _background_summarize(user_id, date_key)

> **权衡：** 非原子持久化。日摘要产生后立即 save 以确保尽早持久化，extra 更新完成后再次 save。若中间崩溃可能丢失 extra 变更但不会丢失日摘要。与旧代码中 extra 与向量非原子持久化的问题一致，属已知折中。

```python
async def _background_summarize(self, user_id: str, date_key: str) -> None:
    try:
        # 日摘要：尽早持久化（优先级高于原子性）
        text = await self._summarizer.get_daily_summary(user_id, date_key)
        if text:
            emb = await self._embedding_client.encode(text)
            await self._index_manager.add_vector(user_id, text, emb, timestamp=date_key, extra_meta={"type": "daily_summary", "source": f"summary_{date_key}"})
            await self._index_manager.save(user_id)

        # extra 更新：全部完成后再 save
        await self._summarizer.get_overall_summary(user_id)
        await self._summarizer.get_daily_personality(user_id, date_key)
        await self._summarizer.get_overall_personality(user_id)
        await self._index_manager.save(user_id)
    except Exception:
        logger.exception("background summarization failed for user=%s", user_id)
```

### 4. RetrievalPipeline

#### 构造函数

```python
def __init__(
    self,
    index_manager: FaissIndexManager,
    embedding_client: EmbeddingClient,
) -> None
```

#### search 方法

```python
async def search(
    self,
    user_id: str,
    query: str,
    top_k: int = 5,
    reference_date: str | None = None,
) -> list[dict]
```

#### 变更点

1. 通过 `index_manager.get_metadata(user_id)` 拿 metadata 副本
2. 通过 `index_manager.search(user_id, ...)` 执行 FAISS 检索
3. `_update_memory_strengths` 改为 `_compute_strength_updates`：纯函数，返回 `{meta_idx: {"memory_strength": new, "last_recall_date": date}}`
4. 返回 `(merged_results, strength_updates)` 元组
5. store 层调用 `index_manager.batch_update_metadata(user_id, strength_updates)` 应用更新
6. store 层负责 save

#### 算法不变

- COARSE_SEARCH_FACTOR = 4
- 四阶段管道：粗排 → 邻居合并 → 并查集去重 → 说话人降权
- 自适应 chunk_size（P90 × 3）
- 降权因子：正分 ×0.75，负分 ×1.25

### 5. Summarizer

#### 构造函数

```python
def __init__(
    self,
    llm: LlmClient,
    index_manager: FaissIndexManager,
) -> None
```

#### 方法

| 原方法 | 新方法 |
|--------|--------|
| `get_daily_summary(date_key) -> str \| None` | `get_daily_summary(user_id, date_key) -> str \| None` |
| `get_overall_summary() -> str \| None` | `get_overall_summary(user_id) -> str \| None` |
| `get_daily_personality(date_key) -> str \| None` | `get_daily_personality(user_id, date_key) -> str \| None` |
| `get_overall_personality() -> str \| None` | `get_overall_personality(user_id) -> str \| None` |

#### 数据访问

- `self._index_manager.get_metadata(user_id)` 获取副本
- `self._index_manager.get_extra(user_id)` 获取 extra dict 的**可变引用**，直接修改后由 `_background_summarize` 末尾 `save` 持久化。不提供 `update_extra` 方法——extra 是 dict，原地修改后 save 即可。

#### 不可变保护（不变）

- daily_summary 已存在（source == `summary_{date}`）则跳过
- overall_summary / overall_personality 已存在则跳过
- 空 LLM 结果：daily 不记录，overall 存 `GENERATION_EMPTY` 哨兵

### 6. forget.py

#### 保留

- `forgetting_retention(days, strength)` 全局函数
- `ForgetMode` 枚举
- `compute_ingestion_forget_ids(metadata, reference_date, rng, mode)` 纯函数
- `SOFT_FORGET_THRESHOLD = 0.15`
- `FORGETTING_TIME_SCALE = 1`

#### 删除

- `ForgettingCurve` 类（含 `maybe_forget` 软标记路径，节流逻辑在实时场景下无意义）
- `FORGET_INTERVAL_SECONDS` 常量
- `_resolve_forget_mode` 函数（mode 由 store 决定）
- store 中 `_purge_forgotten` 方法（软标记路径，与 `_forget_at_ingestion` 硬删除重叠）

### 7. LlmClient + EmbeddingClient（不变）

无变更。

### 8. singleton.py

```python
_memory_store_state: list[MemoryBankStore | None] = [None]
_memory_store_lock = threading.Lock()

def get_memory_store() -> MemoryBankStore:
    if _memory_store_state[0] is None:
        with _memory_store_lock:
            if _memory_store_state[0] is None:
                _memory_store_state[0] = MemoryBankStore(
                    data_dir=DATA_DIR,
                    embedding_model=get_cached_embedding_model(),
                    chat_model=get_chat_model(),
                )
    return _memory_store_state[0]
```

### 9. __init__.py

```python
from app.memory.memory_bank import MemoryBankStore
from app.memory.schemas import (
    InteractionRecord,
    InteractionResult,
    MemoryEvent,
    SearchResult,
)

__all__ = [
    "InteractionRecord",
    "InteractionResult",
    "MemoryEvent",
    "MemoryBankStore",
    "SearchResult",
]
```

---

## 算法等价性保证

以下算法与 VehicleMemBench memorybank.py **逻辑等价**：

1. 遗忘曲线：`R = exp(-days / (FORGETTING_TIME_SCALE * strength))`
2. 邻居合并：双向收集同 source → deque 从外向内裁剪 → `\x00` 分隔
3. 重叠去重：并查集 → 取最高分为 base → 合并 indices/text/speakers/strength
4. 说话人降权：正分 ×0.75，负分 ×1.25
5. 记忆强度：每次召回 +1，更新 last_recall_date
6. 自适应 chunk_size：P90 × 3，[200, 8192]，需 10+ 条目
7. LLM 4 消息序列 + 截断重试
8. 对话格式化：`Conversation content on {date}:[|Speaker|]: text`
9. 摘要/人格 prompt（车辆偏好聚焦）
10. 整体上下文注入（overall_summary + overall_personality 前置为 score=inf）

---

## 调用方影响

所有调用 `MemoryModule` 的代码需改为直接使用 `MemoryBankStore`：

```python
# 旧
await memory.write(event, mode=MemoryMode.MEMORY_BANK)
await memory.search(query)

# 新
await store.write(user_id, event)
await store.search(user_id, query)
```

需更新的调用方：
- API 路由中通过 `get_memory_module()` 获取实例的代码
- 测试文件
