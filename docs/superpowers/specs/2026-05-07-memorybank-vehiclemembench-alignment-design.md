# MemoryBank VehicleMemBench 对齐设计

## 概述

将 thesis-cockpit-memo 的 MemoryBank 实现与 VehicleMemBench 实验组的 MemoryBank
进行功能对齐。三个 Phase 分步交付。

## 三阶段范围

```
Phase 1 ─── P0 正确性修复 + P2-1 维度校正
              (可直接运行, 无行为变化)

Phase 2 ─── P1-2 多用户说话人解析 + 存储格式
              (核心功能, 接口扩展)

Phase 3 ─── P1-1 搜索评分集成遗忘曲线
              (排序改进, 独立验证)
```

---

## Phase 1: 正确性修复

### 1a. `_update_memory_strengths` 刷新 `last_recall_date`

**文件**: `app/memory/stores/memory_bank/retrieval.py`

**现状**: `_update_memory_strengths()` 只递增 `memory_strength`,
不更新 `last_recall_date`。

**改动**: 在递增 strength 后设置 `last_recall_date` 为当天 UTC 日期。

```python
from datetime import UTC, datetime

today_str = datetime.now(UTC).strftime("%Y-%m-%d")
# 在 capped != old 分支内追加:
metadata[mi]["last_recall_date"] = today_str
```

### 1b. 已遗忘条目从 FAISS 硬删除

**文件**: `app/memory/stores/memory_bank/store.py`

**现状**: `maybe_forget()` 仅在 metadata 中设 `forgotten=True`,
不操作 FAISS 索引。三条调用路径（`search` / `write_interaction` / `write`）
的返回值 `forgotten_ids` 均被忽略。

**改动**:
- 统一调用模式: 先 `maybe_forget` 标记元数据, 再 `remove_vectors` 硬删除
- 确定性模式下遍历 metadata 收集 `forgotten=True` 的 ID, 调用 `remove_vectors`
- 概率模式下直接传 `forgotten_ids` 给 `remove_vectors`
- 抽取为私有方法 `_purge_forgotten(metadata) → list[int]`

```python
async def _purge_forgotten(self, metadata: list[dict]) -> None:
    forgotten_ids = self._forget.maybe_forget(metadata)
    if forgotten_ids is None:  # 节流跳过
        return
    if not forgotten_ids:  # 确定性模式: 收集软标记的 ID
        forgotten_ids = [
            m["faiss_id"] for m in metadata
            if m.get("forgotten") and "faiss_id" in m
        ]
    if forgotten_ids:
        await self._index.remove_vectors(forgotten_ids)

# 然后在 search / write_interaction / write 中调用 self._purge_forgotten()
# 替代现有的 self._forget.maybe_forget() 直接调用
```

### 1c. 嵌入维度自动校正

**文件**: `app/memory/stores/memory_bank/faiss_index.py`

**现状**: `DEFAULT_EMBEDDING_DIM = 1536` 硬编码, `add_vector` 不做维度校验。

**改动**: `add_vector` 检测维度不匹配时自动重建索引。

```python
async def add_vector(self, text, embedding, timestamp, extra_meta=None):
    emb_dim = len(embedding)
    if self._index is None:
        self._index = faiss.IndexIDMap(faiss.IndexFlatIP(emb_dim))
    elif self._index.d != emb_dim:
        logger.warning("嵌入维度 %d→%d, 重建索引", self._index.d, emb_dim)
        self._index = faiss.IndexIDMap(faiss.IndexFlatIP(emb_dim))
        self._metadata.clear()
        self._id_to_meta.clear()
        self._next_id = 0
    ...后续逻辑不变...
```

---

## Phase 2: 多用户说话人解析

### 2a. 发言行解析器

**文件**: `app/memory/stores/memory_bank/faiss_index.py`（新增静态方法）

从 VehicleMemBench 移植:

```python
@staticmethod
def parse_speaker_line(line: str) -> tuple[str | None, str]:
    """从 "Speaker: content" 格式解析说话人和内容。"""
    colon_pos = line.find(": ")
    if colon_pos > 0:
        return line[:colon_pos].strip(), line[colon_pos + 2:].strip()
    return None, line.strip()
```

### 2b. 说话人缓存

**文件**: `app/memory/stores/memory_bank/faiss_index.py`

```python
class FaissIndex:
    def __init__(self, ...):
        ...
        self._all_speakers: set[str] = set()

    async def add_vector(self, ...):
        ...
        for spk in extra_meta.get("speakers", []):
            self._all_speakers.add(spk)

    def get_all_speakers(self) -> list[str]:
        return sorted(self._all_speakers)
```

### 2c. `write_interaction` 支持多说话人

**文件**: `app/memory/stores/memory_bank/store.py`

```python
async def write_interaction(
    self, query: str, response: str, event_type: str = "reminder",
    *, user_name: str | None = None, ai_name: str = "AI",
) -> InteractionResult:
    speaker_user = user_name or "User"
    text = (f"Conversation content on {date_key}:"
            f"[|{speaker_user}|]: {query}; [|{ai_name}|]: {response}")
    extra_meta = {
        "source": date_key,
        "speakers": [speaker_user, ai_name],
        "raw_content": query,
        "event_type": event_type,
    }
    ...
```

### 2d. `write` 支持多行发言解析

**文件**: `app/memory/stores/memory_bank/store.py`

若 `event.content` 为多行 `Speaker: content\n...` 格式, 自动解析并逐个
添加向量, 否则保持单条模式。

### 2e. 摘要 prompt 适配多用户

**文件**: `app/memory/stores/memory_bank/summarizer.py`

```python
@staticmethod
def _summarize_prompt(text: str) -> str:
    return (
        "Please summarize the following in-car dialogue concisely, "
        "focusing specifically on:\n"
        "1. Vehicle settings or preferences mentioned (seat position, "
        "climate temperature/ventilation, ambient light color, navigation "
        "mode, music/radio settings, HUD brightness, etc.)\n"
        "2. Which person (by name) expressed or changed each preference\n"  # ← 强化
        "3. Any conflicts or differences between users' vehicle preferences\n"
        "4. Conditional constraints (e.g. preference depends on time of day, "
        "weather, or passenger presence)\n"
        "Ignore general conversation topics unrelated to the vehicle.\n"
        f"Dialogue content:\n{text}\n"
        "Summarization: "
    )

@staticmethod
def _personality_prompt(text: str) -> str:
    return (
        "Based on the following in-car dialogue, analyze the users' "
        "vehicle-related preferences and habits:\n"
        "1. What vehicle settings does each user prefer?\n"         # ← "each user"
        "2. How do their preferences vary by context?\n"
        "3. What driving or comfort habits are exhibited?\n"
        "4. What response strategy should the AI use to anticipate "
        "each user's needs?\n"
        f"Dialogue content:\n{text}\n"
        "Analysis:"
    )
```

### 2f. MemoryEvent 协议扩展

**文件**: `app/memory/schemas.py`

```python
class MemoryEvent(BaseModel):
    ...
    speaker: str = ""  # 新增, 发言者姓名
```

**文件**: `app/memory/interfaces.py`

```python
class MemoryStore(Protocol):
    async def write_interaction(
        self, query: str, response: str, event_type: str = "reminder",
        **kwargs,  # ← 增加 kwargs 保证向后兼容
    ) -> InteractionResult:
        ...
```

---

## Phase 3: 搜索评分集成遗忘曲线

### 3a. `_apply_retention_weight`

**文件**: `app/memory/stores/memory_bank/retrieval.py`

```python
@staticmethod
def _apply_retention_weight(results: list[dict]) -> list[dict]:
    """将遗忘曲线保留率作为连续权重乘入分数。"""
    from datetime import date
    from app.memory.stores.memory_bank.forget import forgetting_retention

    today = date.today()
    for r in results:
        ts = (r.get("last_recall_date") or r.get("timestamp", "") or "")[:10]
        try:
            days = (today - date.fromisoformat(ts)).days
        except (ValueError, TypeError):
            days = 0
        retention = forgetting_retention(max(days, 0),
                                         r.get("memory_strength", 1))
        r["score"] = r["score"] * retention
    return results
```

### 3b. 调用位置

在 `RetrievalPipeline.search()` 中：

```python
results = await self._index.search(query_emb, coarse_k)   # 阶段1: 粗排
merged = self._merge_neighbors(results, metadata)          # 阶段2: 邻居合并
merged = self._apply_retention_weight(merged)              # ← 新增, 在合并后
merged = self._apply_speaker_filter(merged, query)         # 阶段4: 说话人降权
```

---

## 验证计划

| Phase | 验证项 | 方法 |
|-------|--------|------|
| 1a | `last_recall_date` 更新 | 固定 seed mock search, 断言 metadata 中 last_recall_date 变化 |
| 1b | FAISS 硬删除 | 写入 → 遗忘 → 断言 index.ntotal 减少, search 不返回 |
| 1c | 维度校正 | 以 1536 维写入 → 以 3072 维写入 → 索引重建 |
| 2 | 多说话人存储与检索 | `write_interaction(user_name="Gary")` → search 结果含 Gary |
| 2e | 说话人降权 | query 含 "Gary" → 非 Gary 条目分数 *0.75 |
| 3 | 遗忘曲线入排序 | 同 similarity 两个条目, strength 不同 → 排序不同 |

---

## 不在此范围

- 多用户隔离（每用户独立索引）— 当前单用户架构足够
- Summary 连带遗忘 — DEV.md 评估"保留更安全"
- 关键词搜索回退 — 有 embedding 时无需
- `_NAME_BONUS=1.3` / `_RECENCY_DECAY` — 与遗忘曲线重复
- L2 索引迁移警告 — thesis-cockpit-memo 当前无 L2 索引历史

---

## 测试新增清单

### Phase 1 新增测试

- `tests/stores/test_retrieval.py`:
  - `test_update_memory_strength_refreshes_recall_date`
  - `test_retention_weight_affects_ranking`
- `tests/stores/test_faiss_index.py`:
  - `test_dimension_mismatch_rebuilds_index`
- `tests/stores/test_forget.py`:
  - `test_hard_delete_reduces_ntotal`（需要集成 FaissIndex）

### Phase 2 新增测试

- `tests/stores/test_memory_bank_store.py`:
  - `test_write_interaction_with_user_name`
  - `test_search_speaker_filter_reduces_other_users`
- `tests/test_components.py`:
  - `test_parse_speaker_line_valid`
  - `test_parse_speaker_line_invalid`
- `tests/stores/test_summarizer.py`:
  - `test_summary_prompt_includes_user_name`（mock LLM 检查 prompt 含用户）

### Phase 3 新增测试

- `tests/stores/test_retrieval.py`:
  - `test_retention_weight_ranks_by_strength`

---

## 文件改动总览

| 文件 | Phase | 改动类型 |
|------|-------|---------|
| `app/memory/stores/memory_bank/retrieval.py` | 1, 3 | 修改 `_update_memory_strengths`, 新增 `_apply_retention_weight` |
| `app/memory/stores/memory_bank/store.py` | 1, 2 | 重构遗忘调用, 扩展 `write_interaction`, `write` |
| `app/memory/stores/memory_bank/faiss_index.py` | 1, 2 | 维度校正, 说话人缓存, 新增 `parse_speaker_line` |
| `app/memory/stores/memory_bank/summarizer.py` | 2 | prompt 文本更新 |
| `app/memory/schemas.py` | 2 | MemoryEvent 新增 `speaker` 字段 |
| `app/memory/interfaces.py` | 2 | MemoryStore Protocol 增加 `**kwargs` |

---

## 实施顺序

1. Phase 1a （retrieval.py)
2. Phase 1b （store.py)
3. Phase 1c （faiss_index.py)
4. Phase 1 测试
5. `uv run ruff check --fix && uv run ruff format && uv run ty check && uv run pytest`
6. Phase 2a + 2b （faiss_index.py)
7. Phase 2c + 2d （store.py)
8. Phase 2e （summarizer.py)
9. Phase 2f （schemas.py, interfaces.py)
10. Phase 2 测试
11. `uv run ruff check --fix && uv run ruff format && uv run ty check && uv run pytest`
12. Phase 3 （retrieval.py)
13. Phase 3 测试
14. `uv run ruff check --fix && uv run ruff format && uv run ty check && uv run pytest`
