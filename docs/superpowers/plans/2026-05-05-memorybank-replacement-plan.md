# MemoryBank 替换实现计划

> **面向 AI 代理的执行者：** 使用 subagent-driven-development 逐任务实现。
> 步骤使用复选框（`- [ ]`）语法跟踪进度。每步完成后标记。

**目标：** 将现有 MemoryBank 实现（TOML + 暴力搜索）替换为 VehicleMemBench 版
（FAISS IndexFlatIP + 四阶段检索管道），保持 `MemoryModule` Facade 和上层 API 不变。

**架构：** 6 个新模块（faiss_index / retrieval / llm / summarizer / forget / store）
组合实现 `MemoryStore` Protocol。现有 `MemoryModule` / `FeedbackManager` 不变。

**技术栈：** Python 3.14, faiss-cpu, numpy, openai (AsyncOpenAI)

---

### 文件清单

**新建：**
- `app/memory/stores/memory_bank/forget.py` — 遗忘曲线
- `app/memory/stores/memory_bank/llm.py` — LLM 调用封装
- `app/memory/stores/memory_bank/faiss_index.py` — FAISS 索引管理
- `app/memory/stores/memory_bank/retrieval.py` — 四阶段检索管道
- `app/memory/stores/memory_bank/summarizer.py` — 摘要与人格生成

**重写：**
- `app/memory/stores/memory_bank/store.py` — MemoryStore 适配器

**修改：**
- `app/memory/components.py` — 删 EventStorage、SimpleInteractionWriter、forgetting_curve
- `tests/stores/test_memory_bank_store.py` — 重写
- `tests/test_memory_bank.py` — 重写
- `tests/test_components.py` — 删 EventStorage/SimpleInteractionWriter 测试

**删除：**
- `app/memory/stores/memory_bank/engine.py`
- `app/memory/stores/memory_bank/summarization.py`
- `app/memory/stores/memory_bank/personality.py`
- `tests/test_memory_bank_reset.py`

**不变（但确认）：**
- `app/memory/memory.py` / `interfaces.py` / `schemas.py` / `types.py`
- `app/memory/singleton.py` / `utils.py`
- `app/memory/stores/memory_bank/__init__.py` — **确认无 `engine`/`summarization`/`personality` 的 re-export**，若有则清理
- `app/models/embedding.py` / `app/models/chat.py`

**注意：** `tests/stores/` 目录若不存在则新建。

---

### 任务 1：`forget.py` — 遗忘曲线模块

**文件：** 创建 `app/memory/stores/memory_bank/forget.py`

```python
import math
import time
from datetime import UTC, datetime
from typing import Any

SOFT_FORGET_THRESHOLD = 0.15
FORGET_INTERVAL_SECONDS = 300
FORGETTING_TIME_SCALE = 1
# enable_forgetting 由 store.py 在调用 maybe_forget 前检查（默认 false）
# 可通过环境变量 MEMORYBANK_ENABLE_FORGETTING=1 启用


def forgetting_retention(days_elapsed: float, strength: float) -> float:
    if days_elapsed <= 0 or strength <= 0:
        return 1.0 if days_elapsed <= 0 else 0.0
    return math.exp(-days_elapsed / (FORGETTING_TIME_SCALE * strength))


class ForgettingCurve:
    def __init__(self) -> None:
        self._last_forget_time: float = 0.0

    def maybe_forget(self, metadata: list[dict], reference_date: str | None = None) -> list[dict]:
        now = time.monotonic()
        if now - self._last_forget_time < FORGET_INTERVAL_SECONDS:
            return metadata
        self._last_forget_time = now
        today = reference_date or datetime.now(UTC).strftime("%Y-%m-%d")
        for entry in metadata:
            if entry.get("type") in ("daily_summary",):
                continue
            if entry.get("forgotten"):
                continue
            ts = entry.get("last_recall_date") or entry.get("timestamp", "")[:10]
            try:
                days = (datetime.strptime(today[:10], "%Y-%m-%d")
                        - datetime.strptime(ts[:10], "%Y-%m-%d")).days
            except (ValueError, TypeError):
                continue
            strength = float(entry.get("memory_strength", 1))
            retention = forgetting_retention(days, strength)
            if retention < SOFT_FORGET_THRESHOLD:
                entry["forgotten"] = True
        return metadata
```

- [ ] **步骤 1：编写 forger.py 并验证语法**
  `uv run python -c "import ast; ast.parse(open('app/memory/stores/memory_bank/forget.py').read()); print('OK')"`

---

### 任务 2：`llm.py` — LLM 调用封装

**文件：** 创建 `app/memory/stores/memory_bank/llm.py`

```python
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.chat import ChatModel

logger = logging.getLogger(__name__)

LLM_MAX_RETRIES = 3
LLM_MAX_TOKENS = 400
LLM_TEMPERATURE = 0.7
LLM_TRIM_START = 1800
LLM_TRIM_STEP = 200
LLM_TRIM_MIN = 500


class LlmClient:
    def __init__(self, chat_model: ChatModel) -> None:
        self._chat_model = chat_model

    async def call(self, prompt: str, *, system_prompt: str | None = None) -> str | None:
        """调用 ChatModel.generate()，重试时自动截断 prompt 末尾上下文。"""
        for attempt in range(LLM_MAX_RETRIES):
            try:
                resp = await self._chat_model.generate(
                    prompt=prompt,
                    system_prompt=system_prompt or None,
                )
                return resp.strip() if resp else ""
            except Exception as exc:
                err = str(exc).lower()
                is_ctx = any(p in err for p in ("maximum context", "context length",
                              "too long", "reduce the length", "input length"))
                if is_ctx and attempt < LLM_MAX_RETRIES - 1:
                    prompt = prompt[-max(LLM_TRIM_START - LLM_TRIM_STEP * attempt, LLM_TRIM_MIN):]
                    continue
                if attempt < LLM_MAX_RETRIES - 1:
                    continue
                logger.warning("LlmClient failed after %d retries", LLM_MAX_RETRIES)
                return None
        return None
```

- [ ] **步骤 1：编写 llm.py 并验证语法**

---

### 任务 3：`faiss_index.py` — FAISS 索引管理

**文件：** 创建 `app/memory/stores/memory_bank/faiss_index.py`

```python
import json
import logging
from pathlib import Path
from typing import Any

import faiss
import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_DIM = 1536


class FaissIndex:
    def __init__(self, data_dir: Path, embedding_dim: int = DEFAULT_EMBEDDING_DIM) -> None:
        self._data_dir = data_dir
        self._dim = embedding_dim
        self._index: faiss.IndexIDMap | None = None
        self._metadata: list[dict] = []
        self._extra: dict = {}
        self._next_id: int = 0
        self._id_to_meta: dict[int, int] = {}

    async def load(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        ip = self._data_dir / "index.faiss"
        mp = self._data_dir / "metadata.json"
        ep = self._data_dir / "extra_metadata.json"

        ok = False
        if ip.exists() and mp.exists():
            try:
                idx = faiss.read_index(str(ip))
                with open(mp) as f:
                    meta = json.load(f)
                if not isinstance(meta, list):
                    raise TypeError
                for i, m in enumerate(meta):
                    if not isinstance(m, dict) or "faiss_id" not in m:
                        raise ValueError(f"entry {i}: invalid")
                if idx.ntotal != len(meta):
                    raise ValueError(f"count mismatch {idx.ntotal} vs {len(meta)}")
                self._index = idx
                self._metadata = meta
                self._next_id = (max(m["faiss_id"] for m in meta) + 1) if meta else 0
                self._id_to_meta = {m["faiss_id"]: i for i, m in enumerate(meta)}
                if ep.exists():
                    with open(ep) as f:
                        e = json.load(f)
                    self._extra = e if isinstance(e, dict) else {}
                ok = True
            except Exception as exc:
                logger.warning("FaissIndex corrupted, rebuilding: %s", exc)
        if not ok:
            self._index = faiss.IndexIDMap(faiss.IndexFlatIP(self._dim))
            self._metadata = []
            self._extra = {}
            self._next_id = 0
            self._id_to_meta = {}

    async def save(self) -> None:
        if self._index is None:
            return
        faiss.write_index(self._index, str(self._data_dir / "index.faiss"))
        with open(self._data_dir / "metadata.json", "w") as f:
            json.dump(self._metadata, f, ensure_ascii=False, indent=2)
        if self._extra:
            with open(self._data_dir / "extra_metadata.json", "w") as f:
                json.dump(self._extra, f, ensure_ascii=False, indent=2)

    async def add_vector(self, text: str, embedding: list[float],
                         timestamp: str, extra_meta: dict | None = None) -> int:
        fid = self._next_id
        self._next_id += 1
        vec = np.array([embedding], dtype=np.float32)
        faiss.normalize_L2(vec)
        self._index.add_with_ids(vec, np.array([fid], dtype=np.int64))
        entry = {"faiss_id": fid, "text": text, "timestamp": timestamp,
                 "memory_strength": 1,
                 "last_recall_date": timestamp[:10] if len(timestamp) >= 10 else timestamp}
        if extra_meta:
            entry.update(extra_meta)
        self._metadata.append(entry)
        self._id_to_meta[fid] = len(self._metadata) - 1
        return fid

    async def search(self, query_emb: list[float], top_k: int) -> list[dict]:
        if self._index is None or self._index.ntotal == 0:
            return []
        k = min(top_k, self._index.ntotal)
        vec = np.array([query_emb], dtype=np.float32)
        faiss.normalize_L2(vec)
        scores, indices = self._index.search(vec, k)
        results = []
        for s, fid in zip(scores[0], indices[0]):
            mi = self._id_to_meta.get(int(fid))
            if mi is None:
                continue
            m = dict(self._metadata[mi])
            m["score"] = float(s)
            m["_meta_idx"] = mi
            results.append(m)
        return results

    async def update_metadata(self, faiss_id: int, updates: dict) -> None:
        mi = self._id_to_meta.get(faiss_id)
        if mi is not None:
            self._metadata[mi].update(updates)

    async def remove_vectors(self, faiss_ids: list[int]) -> None:
        id_arr = np.array(faiss_ids, dtype=np.int64)
        self._index.remove_ids(id_arr)
        id_set = set(faiss_ids)
        self._metadata = [m for m in self._metadata if m["faiss_id"] not in id_set]
        self._id_to_meta = {m["faiss_id"]: i for i, m in enumerate(self._metadata)}

    def get_metadata(self) -> list[dict]:
        return self._metadata

    def get_extra(self) -> dict:
        return self._extra

    def set_extra(self, extra: dict) -> None:
        self._extra = extra

    @property
    def total(self) -> int:
        return self._index.ntotal if self._index else 0
```

- [ ] **步骤 1：编写 faiss_index.py 并验证语法**
- [ ] **步骤 2：编写测试** `tests/stores/test_faiss_index.py`
  - `test_load_creates_new_index_when_no_files`
  - `test_add_vector_and_search`
  - `test_save_and_load_persistence`
  - `test_corrupted_metadata_rebuilds`
- [ ] **步骤 3：运行测试通过** `uv run pytest tests/stores/test_faiss_index.py -v`

---

### 任务 4：`retrieval.py` — 四阶段检索管道

**文件：** 创建 `app/memory/stores/memory_bank/retrieval.py`

核心逻辑直接移植自 VMB 源码。源文件路径：
`/home/miyakomeow/Codes/VehicleMemBench/evaluation/memorysystems/memorybank.py`

需搬运的函数（均为纯 dict/list 操作，无外部依赖，直接复制 + 适配类型注解）：

| 函数 | VMB 行号 | 功能 |
|------|---------|------|
| `_merge_overlapping_results()` | 374-500 | 并查集跨结果重叠消除 |
| `_merge_neighbors()` 的合并核心逻辑 | 839-952 | 同 source 邻居合并 + deque 裁剪 |
| `_strip_source_prefix()` | 355-371 | 去除文本前缀标记 |
| `_clean_search_result()` | 1596-1603 | 移除内部字段，解码分隔符 |
| `_word_in_text()` | 274-278 | 单词边界匹配 |

`_merge_neighbors` 适配：VMB 接受 `results + user_id` 后取 `self._metadata`；本项目 `FaissIndex` 直接提供 `get_metadata()`，调用处改为 `metadata = self._index.get_metadata()`。

接口：
```python
class RetrievalPipeline:
    def __init__(self, index: FaissIndex, embedding_model: EmbeddingModel)
    async def search(query: str, top_k: int = 5) -> list[dict]
```

四阶段 inline：
1. `embedding_model.encode(query)` + `index.search(emb, top_k * 4)`
2. `_merge_neighbors(results)` — 同 source 邻居合并
3. `_merge_overlapping(results)` — 并查集跨结果去重
4. `_speaker_filter(results, query)` — query 匹配说话人时降权不相关条目
5. 截断 + 更新 memory_strength + `_clean_result()` + `index.save()`

常量：
- `COARSE_SEARCH_FACTOR = 4`
- `_MERGED_TEXT_DELIMITER = "\\x00"`
- `DEFAULT_CHUNK_SIZE = 1500`（可被环境变量 `MEMORYBANK_CHUNK_SIZE` 覆盖）

`_resolve_chunk_size()`: 从 `os.getenv("MEMORYBANK_CHUNK_SIZE")` 读取，无效/未设置时回退 `DEFAULT_CHUNK_SIZE`。

- [ ] **步骤 1：编写 retrieval.py**（从 VMB memorybank.py 搬运 `_merge_neighbors`、`_merge_overlapping_results`、`_strip_source_prefix`、`_clean_result`、`_word_in_text`，适配 `FaissIndex` 接口）
- [ ] **步骤 2：验证语法**
- [ ] **步骤 3：编写测试** `tests/stores/test_retrieval.py`
  - `test_empty_index_returns_empty`
  - `test_merge_overlapping_dedup`
- [ ] **步骤 4：运行测试通过**

---

### 任务 5：`summarizer.py` — 摘要与人格生成

**文件：** 创建 `app/memory/stores/memory_bank/summarizer.py`

```python
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .faiss_index import FaissIndex
    from .llm import LlmClient

logger = logging.getLogger(__name__)
_GENERATION_EMPTY = "GENERATION_EMPTY"
_SUMMARY_SYSTEM_PROMPT = (
    "You are an in-car AI assistant with expertise in remembering "
    "vehicle preferences, driving habits, and in-car conversation context."
)


class Summarizer:
    def __init__(self, llm: LlmClient, index: FaissIndex) -> None:
        self._llm = llm
        self._index = index

    async def get_daily_summary(self, date_key: str) -> str | None:
        """生成 date_key 的每日摘要。已有则返回 None。"""
        meta = self._index.get_metadata()
        if any(m.get("source") == f"summary_{date_key}" for m in meta):
            return None
        texts = [m["text"] for m in meta
                 if m.get("source") == date_key and m.get("type") != "daily_summary"]
        if not texts:
            return None
        result = await self._llm.call(self._summarize_prompt("\n".join(texts)),
                                      system_prompt=_SUMMARY_SYSTEM_PROMPT)
        if result:
            return f"The summary of the conversation on {date_key} is: {result}"
        return None

    async def get_overall_summary(self) -> str | None:
        """生成总体摘要。已有则返回 None。"""
        extra = self._index.get_extra()
        if extra.get("overall_summary"):
            return None
        meta = self._index.get_metadata()
        daily_sums = [m for m in meta if m.get("type") == "daily_summary"]
        if not daily_sums:
            return None
        prompt = "Please provide a highly concise summary...\\n"
        for m in daily_sums:
            prompt += f"\\n{m.get('text', '')}"
        prompt += "\\nSummarization: "
        result = await self._llm.call(prompt, system_prompt=_SUMMARY_SYSTEM_PROMPT)
        if result:
            extra["overall_summary"] = result
            return result
        extra["overall_summary"] = _GENERATION_EMPTY
        return None

    async def get_daily_personality(self, date_key: str) -> str | None:
        """生成 date_key 的单日人格分析。已有则返回 None。"""
        extra = self._index.get_extra()
        existing = extra.setdefault("daily_personalities", {})
        if date_key in existing:
            return None
        texts = [m["text"] for m in self._index.get_metadata()
                 if m.get("source") == date_key and m.get("type") != "daily_summary"]
        if not texts:
            return None
        result = await self._llm.call(self._personality_prompt("\n".join(texts)),
                                      system_prompt=_SUMMARY_SYSTEM_PROMPT)
        if result:
            existing[date_key] = result
            return result
        return None

    async def get_overall_personality(self) -> str | None:
        """生成总体人格画像。已有则返回 None。"""
        extra = self._index.get_extra()
        if extra.get("overall_personality"):
            return None
        dailies = extra.get("daily_personalities", {})
        if not dailies:
            return None
        prompt = "The following are analyses...\\n"
        for date, text in sorted(dailies.items()):
            prompt += f"\\nAt {date}, {text}"
        prompt += "\\nPlease provide a concise summary: "
        result = await self._llm.call(prompt, system_prompt=_SUMMARY_SYSTEM_PROMPT)
        if result:
            extra["overall_personality"] = result
            return result
        extra["overall_personality"] = _GENERATION_EMPTY
        return None

    @staticmethod
    def _summarize_prompt(text: str) -> str:
        return (f"Please summarize the following in-car dialogue concisely, "
                f"focusing on vehicle settings, user preferences, conflicts, "
                f"and conditional constraints. Ignore unrelated topics.\\n"
                f"Dialogue content:\\n{text}\\nSummarization：")

    @staticmethod
    def _personality_prompt(text: str) -> str:
        return (f"Based on the following in-car dialogue, analyze the users' "
                f"vehicle-related preferences and habits:\\n"
                f"1. What vehicle settings does each user prefer?\\n"
                f"2. How do preferences vary by context?\\n"
                f"3. What driving or comfort habits are exhibited?\\n"
                f"Dialogue content:\\n{text}\\nAnalysis:")
```

- [ ] **步骤 1：编写 summarizer.py**
- [ ] **步骤 2：验证语法**

---

### 任务 6：`store.py` — MemoryStore 适配器

**文件：** 重写 `app/memory/stores/memory_bank/store.py`

```python
import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.memory.components import FeedbackManager
from app.memory.schemas import (
    FeedbackData, InteractionResult, MemoryEvent, SearchResult,
)
from app.memory.stores.memory_bank.forget import ForgettingCurve

if TYPE_CHECKING:
    from pathlib import Path
    from app.models.chat import ChatModel
    from app.models.embedding import EmbeddingModel

logger = logging.getLogger(__name__)


class MemoryBankStore:
    store_name = "memory_bank"
    requires_embedding = True
    requires_chat = True
    supports_interaction = True

    def __init__(self, data_dir: Path, embedding_model: EmbeddingModel | None = None,
                 chat_model: ChatModel | None = None, **kwargs: Any) -> None:
        from .faiss_index import FaissIndex
        from .retrieval import RetrievalPipeline
        from .llm import LlmClient
        from .summarizer import Summarizer

        self._data_dir = data_dir
        self._index = FaissIndex(data_dir)
        self._forget = ForgettingCurve()
        self._feedback = FeedbackManager(data_dir)
        self._embedding_model = embedding_model
        self._chat_model = chat_model
        self._retrieval = RetrievalPipeline(self._index, embedding_model) if embedding_model else None
        self._llm = LlmClient(chat_model) if chat_model else None
        self._summarizer = Summarizer(self._llm, self._index) if self._llm else None

    @property
    def _forgetting_enabled(self) -> bool:
        import os
        return os.getenv("MEMORYBANK_ENABLE_FORGETTING", "0").lower() in ("1", "true", "yes")

    async def write_interaction(self, query: str, response: str,
                                 event_type: str = "reminder") -> InteractionResult:
        await self._index.load()
        date_key = datetime.now(UTC).strftime("%Y-%m-%d")
        ts = datetime.now(UTC).isoformat()
        text = f"Conversation content on {date_key}:[|User|]: {query}; [|AI|]: {response}"
        emb = await self._embedding_model.encode(text)
        fid = await self._index.add_vector(text, emb, ts,
                                            {"source": date_key, "speakers": ["User", "AI"]})
        if self._forgetting_enabled:
            self._forget.maybe_forget(self._index.get_metadata())
        if self._summarizer:
            asyncio.create_task(self._background_summarize(date_key))
        return InteractionResult(event_id=str(fid))

    async def _background_summarize(self, date_key: str) -> None:
        """异步后台任务：生成摘要/人格并持久化。"""
        try:
            text = await self._summarizer.get_daily_summary(date_key)
            if text:
                emb = await self._embedding_model.encode(text)
                await self._index.add_vector(text, emb, f"{date_key}T00:00:00",
                                             {"type": "daily_summary", "source": f"summary_{date_key}"})
            await self._summarizer.get_overall_summary()
            await self._summarizer.get_daily_personality(date_key)
            await self._summarizer.get_overall_personality()
            await self._index.save()
        except Exception:
            logger.exception("background summarization failed")

    async def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        await self._index.load()
        if self._index.total == 0 or not self._retrieval:
            return []
        # 搜索前触发遗忘曲线
        if self._forgetting_enabled:
            self._forget.maybe_forget(self._index.get_metadata())
        results = await self._retrieval.search(query, top_k + 1)
        extra = self._index.get_extra()
        prepend = []
        for key, label in [("overall_summary", "Overall summary of past memories"),
                            ("overall_personality", "User vehicle preferences and habits")]:
            val = extra.get(key, "")
            if val and val != "GENERATION_EMPTY":
                prepend.append(f"{label}: {val}")
        out: list[SearchResult] = []
        if prepend:
            out.append(SearchResult(event={"content": "\n".join(prepend), "type": "overall_context"},
                                     score=float("inf"), source="overall"))
        for r in results:
            out.append(SearchResult(
                event={"content": r.get("text", ""), "source": r.get("source", ""),
                        "memory_strength": int(r.get("memory_strength", 1))},
                score=float(r.get("score", 0.0)), source=r.get("source", "event")))
        return out

    async def write(self, event: MemoryEvent) -> str:
        await self._index.load()
        date_key = datetime.now(UTC).strftime("%Y-%m-%d")
        ts = datetime.now(UTC).isoformat()
        text = f"Conversation content on {date_key}:[|System|]: {event.content}"
        emb = await self._embedding_model.encode(text)
        fid = await self._index.add_vector(text, emb, ts,
                                            {"source": date_key, "speakers": ["System"]})
        if self._forgetting_enabled:
            self._forget.maybe_forget(self._index.get_metadata())
        if self._summarizer:
            asyncio.create_task(self._background_summarize(date_key))
        return str(fid)

    async def get_history(self, limit: int = 10) -> list[MemoryEvent]:
        await self._index.load()
        entries = [m for m in self._index.get_metadata()
                   if m.get("type") != "daily_summary"]
        return [MemoryEvent(content=m.get("text", ""), type="reminder",
                             memory_strength=int(m.get("memory_strength", 1)))
                for m in entries[-limit:]]

    async def update_feedback(self, event_id: str, feedback: FeedbackData) -> None:
        await self._feedback.update_feedback(event_id, feedback)

    async def get_event_type(self, event_id: str) -> str | None:
        await self._index.load()
        for m in self._index.get_metadata():
            if str(m.get("faiss_id")) == event_id:
                return "reminder"
        return None
```

- [ ] **步骤 1：重写 store.py**
- [ ] **步骤 2：验证语法**

---

### 任务 7：清理旧文件

- [ ] **步骤 1：删除废弃文件**
  ```bash
  rm app/memory/stores/memory_bank/engine.py
  rm app/memory/stores/memory_bank/summarization.py
  rm app/memory/stores/memory_bank/personality.py
  rm tests/test_memory_bank_reset.py
  ```
- [ ] **步骤 2：更新 components.py** — 删除 EventStorage、SimpleInteractionWriter、forgetting_curve、ActionRequiredError、DEFAULT_DECAY_BASE。保留 FeedbackManager、KeywordSearch、SUMMARY_WEIGHT。
- [ ] **步骤 3：验证 components.py 可导入**
  ```bash
  uv run python -c "from app.memory.components import FeedbackManager, KeywordSearch, SUMMARY_WEIGHT; print('OK')"
  ```

---

### 任务 8：编写 / 重写测试

- [ ] **步骤 1：编写 `tests/stores/test_forget.py`**
  测试 `ForgettingCurve.maybe_forget()`：0 天不遗忘、15 天低于阈值、摘要条目豁免、节流。
- [ ] **步骤 2：编写 `tests/stores/test_summarizer.py`（标记 `--test-llm`）**
  测试 `Summarizer.get_daily_summary()`：mock LLM 返回内容 → 返回摘要文本；mock LLM 返回空 → 返回 None。
- [ ] **步骤 3：重写 `tests/stores/test_memory_bank_store.py`**
  测试 MemoryStore Protocol 方法：`write_interaction`、`search`、`write`、`get_history`、`get_event_type`
  使用 `AsyncMock` mock embedding_model.encode。
- [ ] **步骤 4：重写 `tests/test_memory_bank.py`**
  集成测试：写交互 → 搜索 → 回忆强化
- [ ] **步骤 5：更新 `tests/test_components.py`**
  删除 EventStorage / SimpleInteractionWriter 相关测试（约 300 行）

---

### 任务 9：集成验证

- [ ] **步骤 1：lint + format**
  ```bash
  uv run ruff check --fix
  uv run ruff format
  ```
- [ ] **步骤 2：类型检查**
  ```bash
  uv run ty check
  ```
- [ ] **步骤 3：运行全部测试**
  ```bash
  uv run pytest -v
  ```
- [ ] **步骤 4：验证导入链**
  ```bash
  uv run python -c "from app.memory.stores.memory_bank.store import MemoryBankStore; from app.memory.memory import MemoryModule; print('全部导入成功')"
  ```
