# 记忆系统全面重写实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 全面重写 `app/memory/memory_bank/` 模块，修复 bug、支持多用户、清理架构债务。

**架构：** FaissIndex 内部按 `user_id` 隔离索引/元数据；retrieval/forget 为纯函数；store.py 唯一编排者；MemoryStore Protocol 加 `user_id` 参数。

**技术栈：** Python 3.14, FAISS (IndexFlatIP), Pydantic, asyncio, pytest

---

## 文件清单

| 文件 | 操作 | 职责 |
|------|------|------|
| `app/memory/memory_bank/retrieval.py` | 重写 | 四阶段检索管道纯函数 |
| `app/memory/memory_bank/forget.py` | 重写 | 统一遗忘纯函数 |
| `app/memory/memory_bank/faiss_index.py` | 重写 | 多用户 FAISS 索引管理 |
| `app/memory/memory_bank/store.py` | 重写 | MemoryBankStore 编排层 |
| `app/memory/memory_bank/summarizer.py` | 重写 | 摘要 + 人格生成 |
| `app/memory/memory_bank/llm.py` | 微调 | 移除未使用常量 |
| `app/memory/embedding_client.py` | 重写 | 真批量 embedding |
| `app/memory/interfaces.py` | 修改 | Protocol 加 user_id |
| `app/memory/memory.py` | 修改 | Facade 透传 user_id |
| `app/memory/components.py` | 修改 | 删除 KeywordSearch |
| `app/memory/utils.py` | 删除 | 无调用方 |
| `app/memory/stores/__init__.py` | 删除 | 空壳 |
| `app/memory/__init__.py` | 修改 | 更新导出 |
| `app/agents/workflow.py` | 修改 | 透传 user_id |
| `app/api/resolvers/query.py` | 修改 | 透传 user_id |
| `app/api/resolvers/mutation.py` | 修改 | 透传 user_id |
| `tests/stores/test_retrieval.py` | 重写 | 纯函数测试 |
| `tests/stores/test_forget.py` | 重写 | 纯函数测试 |
| `tests/stores/test_faiss_index.py` | 重写 | 多用户索引测试 |
| `tests/stores/test_summarizer.py` | 重写 | mock LlmClient |
| `tests/stores/test_memory_bank_store.py` | 重写 | 集成测试 |
| `tests/test_embedding_client.py` | 重写 | 真批量测试 |
| `tests/test_cosine_similarity.py` | 删除 | utils.py 删除后无意义 |

---

### 任务 1：retrieval.py 纯函数重写

**文件：**
- 重写：`app/memory/memory_bank/retrieval.py`
- 测试：`tests/stores/test_retrieval.py`

- [ ] **步骤 1：编写 retrieval.py 接口骨架**

创建 `retrieval.py`，定义所有函数签名和常量，函数体暂用 `raise NotImplementedError`。

关键函数签名：

```python
def _strip_source_prefix(text: str, date_part: str) -> str: ...
def _safe_memory_strength(value: object) -> float: ...
def get_effective_chunk_size(metadata: list[dict]) -> int: ...
def merge_neighbors(results: list[dict], metadata: list[dict], chunk_size: int) -> list[dict]: ...
def _build_overlap_groups(merging: list[dict]) -> dict[int, list[int]]: ...
def _merge_result_group(merging: list[dict], members: list[int]) -> dict | None: ...
def deduplicate_overlaps(results: list[dict]) -> list[dict]: ...
def _penalize_score(score: float) -> float: ...
def _word_in_text(word: str, text: str) -> bool: ...
def apply_speaker_filter(results: list[dict], query: str, all_speakers: list[str]) -> list[dict]: ...
def update_memory_strengths(results: list[dict], metadata: list[dict], reference_date: str | None) -> bool: ...
def clean_search_result(result: dict) -> None: ...
```

常量：`COARSE_SEARCH_FACTOR=4`, `_MERGED_TEXT_DELIMITER="\x00"`, `DEFAULT_CHUNK_SIZE=1500`, `CHUNK_SIZE_MIN=200`, `CHUNK_SIZE_MAX=8192`, `_ADAPTIVE_CHUNK_MIN_ENTRIES=10`, `INITIAL_MEMORY_STRENGTH=1`, `_INTERNAL_KEYS=frozenset(...)`。

实现思路：从现有 `retrieval.py` 提取纯函数逻辑，移除类/状态/持久化调用。修复 `_penalize_score` 为正分 `*0.75` 负分 `*1.25`。

- [ ] **步骤 2：编写 test_retrieval.py 测试**

用固定 metadata 构造测试数据，覆盖以下场景：

- `test_merge_neighbors_single_result`：1 条结果无邻居，透传
- `test_merge_neighbors_same_source`：同 source 3 条连续，合并为 1 条
- `test_merge_neighbors_chunk_size_trim`：超出 chunk_size 时从两端裁剪
- `test_deduplicate_overlaps_no_overlap`：无重叠透传
- `test_deduplicate_overlaps_shared_index`：两结果共享 index → 并查集合并
- `test_speaker_filter_no_match`：query 无说话人名，不惩罚
- `test_speaker_filter_positive_score`：正分不相关条目 `*0.75`
- `test_speaker_filter_negative_score`：负分不相关条目 `*1.25`
- `test_update_memory_strengths_increment`：命中条目 strength +1
- `test_update_memory_strengths_updates_recall_date`：更新 last_recall_date
- `test_clean_search_result_removes_internal_keys`：移除 `_meta_idx`/`_merged_indices` 等
- `test_clean_search_result_decodes_delimiter`：`\x00` → `"; "`
- `test_strip_source_prefix_conversation`：剥离 `Conversation content on ...:` 前缀
- `test_strip_source_prefix_summary`：剥离 `The summary of the conversation on ... is:` 前缀
- `test_get_effective_chunk_size_adaptive`：P90 × 3
- `test_get_effective_chunk_size_env_override`：环境变量覆盖

- [ ] **步骤 3：实现 retrieval.py 全部函数**

从现有 `retrieval.py` 移植逻辑，移除类、移除 `async`、移除 `FaissIndex` 依赖、移除 `self._index.save()` 调用。所有函数为同步纯函数。

- [ ] **步骤 4：运行测试**

```bash
uv run pytest tests/stores/test_retrieval.py -v
```

预期：全部 PASS。

- [ ] **步骤 5：lint + type check**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```

- [ ] **步骤 6：commit**

```
refactor: rewrite retrieval.py as pure functions
```

---

### 任务 2：forget.py 统一遗忘重写

**文件：**
- 重写：`app/memory/memory_bank/forget.py`
- 测试：`tests/stores/test_forget.py`

- [ ] **步骤 1：编写 forget.py 接口骨架**

```python
import enum
import math
import random
import logging
from datetime import date

logger = logging.getLogger(__name__)

class ForgetMode(enum.Enum):
    DETERMINISTIC = "deterministic"
    PROBABILISTIC = "probabilistic"

def forgetting_retention(days_elapsed: float, strength: float) -> float:
    """R = e^{-t/S}，对齐原论文公式。"""

def compute_forget_ids(
    metadata: list[dict],
    reference_date: str,
    *,
    mode: ForgetMode = ForgetMode.DETERMINISTIC,
    rng: random.Random | None = None,
    threshold: float = 0.15,
) -> list[int]:
    """遍历 metadata，返回应硬删除的 faiss_id 列表。跳过 daily_summary。"""

def compute_reference_date(metadata: list[dict]) -> str:
    """从 metadata 时间戳推算参考日期（最大日期 +1 天）。"""
```

实现思路：从现有 `forget.py` 合并 `compute_ingestion_forget_ids` 和 `ForgettingCurve.maybe_forget` 为单一 `compute_forget_ids`。删除节流/软标记逻辑。`forgetting_retention` 保持 `math.exp(-days / strength)` 不变。

- [ ] **步骤 2：编写 test_forget.py 测试**

- `test_forgetting_retention_zero_days`：0 天 → 返回 1.0
- `test_forgetting_retention_zero_strength`：0 强度 → 返回 0.0
- `test_forgetting_retention_decay`：验证衰减趋势
- `test_compute_forget_ids_deterministic_below_threshold`：retention < 0.15 → 删除
- `test_compute_forget_ids_deterministic_above_threshold`：retention ≥ 0.15 → 保留
- `test_compute_forget_ids_skips_daily_summary`：daily_summary 条目跳过
- `test_compute_forget_ids_probabilistic_with_seed`：固定 seed → 结果可复现
- `test_compute_forget_ids_invalid_date`：无效日期条目保留
- `test_compute_reference_date_basic`：最大日期 +1 天
- `test_compute_reference_date_empty_metadata`：空 metadata → 今天 UTC

- [ ] **步骤 3：实现 forget.py**

- [ ] **步骤 4：运行测试**

```bash
uv run pytest tests/stores/test_forget.py -v
```

- [ ] **步骤 5：lint + type check**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```

- [ ] **步骤 6：commit**

```
refactor: unify forgetting into pure functions
```

---

### 任务 3：faiss_index.py 多用户索引重写

**文件：**
- 重写：`app/memory/memory_bank/faiss_index.py`
- 测试：`tests/stores/test_faiss_index.py`

- [ ] **步骤 1：编写 faiss_index.py 接口骨架**

核心类和数据结构：

```python
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import faiss
import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_DIM = 1536
_TIMESTAMP_LENGTH = 10

@dataclass
class _UserIndex:
    index: faiss.IndexIDMap
    metadata: list[dict]
    next_id: int
    id_to_meta: dict[int, int]
    all_speakers: set[str]
    extra: dict

class FaissIndex:
    def __init__(self, data_dir: Path) -> None: ...
    async def load(self) -> None: ...
    async def reload(self, user_id: str) -> None: ...
    async def save(self, user_id: str) -> None: ...
    async def add_vector(self, user_id: str, text: str, embedding: list[float],
                         timestamp: str, extra_meta: dict | None = None) -> int: ...
    async def search(self, user_id: str, query_emb: list[float], top_k: int) -> list[dict]: ...
    async def remove_vectors(self, user_id: str, faiss_ids: list[int]) -> None: ...
    def get_metadata(self, user_id: str) -> list[dict]: ...
    def get_metadata_by_id(self, user_id: str, faiss_id: int) -> dict | None: ...
    def get_extra(self, user_id: str) -> dict: ...
    def get_all_speakers(self, user_id: str) -> list[str]: ...
    def total(self, user_id: str) -> int: ...
    @staticmethod
    def parse_speaker_line(line: str) -> tuple[str | None, str]: ...
```

实现思路：
- `_indices: dict[str, _UserIndex]` 按 user_id 路由
- 磁盘布局 `{data_dir}/{user_id}/index.faiss|metadata.json|extra_metadata.json`
- `load()` 扫描 data_dir 子目录，每个子目录名即 user_id
- 损坏文件：删除该 user 子目录文件，不预建索引
- `parse_speaker_line` 从现有实现移植（无变化）
- `_dim` 首次 add_vector 锁定，后续不一致抛 ValueError

- [ ] **步骤 2：编写 test_faiss_index.py 测试**

使用 `tmp_path` fixture 创建真实 FAISS 索引。

- `test_add_and_search_single_user`：添加向量后能搜回
- `test_multi_user_isolation`：用户 A 写入不影响用户 B 搜索
- `test_add_vector_dimension_mismatch`：不同维度抛 ValueError
- `test_remove_vectors`：删除后搜索不返回
- `test_save_and_reload`：持久化后重新加载，数据完整
- `test_corrupted_metadata_recovery`：metadata.json 格式错误 → 删除文件 → 返回空
- `test_get_all_speakers`：返回所有 speakers
- `test_get_extra_default_empty`：无 extra 文件返回空 dict
- `test_parse_speaker_line`：正常解析 `"Speaker: content"`
- `test_parse_speaker_line_no_colon`：无冒号返回 `(None, line)`

- [ ] **步骤 3：实现 faiss_index.py**

- [ ] **步骤 4：运行测试**

```bash
uv run pytest tests/stores/test_faiss_index.py -v
```

- [ ] **步骤 5：lint + type check**

- [ ] **步骤 6：commit**

```
refactor: multi-user FaissIndex with per-user isolation
```

---

### 任务 4：embedding_client.py 真批量重写

**文件：**
- 重写：`app/memory/embedding_client.py`
- 测试：`tests/test_embedding_client.py`

- [ ] **步骤 1：编写 embedding_client.py 接口骨架**

```python
import asyncio
import logging
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.embedding import EmbeddingModel

logger = logging.getLogger(__name__)

class EmbeddingClient:
    MAX_RETRIES = 5
    BACKOFF_BASE = 2
    BATCH_SIZE = 100

    def __init__(self, embedding_model: EmbeddingModel, *,
                 rng: random.Random | None = None) -> None: ...

    async def encode(self, text: str) -> list[float]:
        """编码单条，委托给 encode_batch。"""

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """分批编码，每批一次 API 调用。"""

    async def _encode_single_batch(self, texts: list[str]) -> list[list[float]]:
        """单批 API 调用，指数退避重试。"""
```

实现思路：
- `encode` 委托给 `encode_batch([text])[0]`
- `encode_batch` 按 `BATCH_SIZE` 分批，每批调 `_encode_single_batch`
- `_encode_single_batch` 调 `self._model.batch_encode(texts)`（注意：`EmbeddingModel` 方法名为 `batch_encode`，非 `encode_batch`）
- 若 `self._model` 无 `batch_encode` 方法，退化为逐条调 `encode`
- 瞬态错误检测：错误消息匹配 `connection/timeout/rate limit/eof/reset/service unavailable/bad gateway/internal server error`
- 指数退避 + jitter

- [ ] **步骤 2：编写 test_embedding_client.py**

Mock `EmbeddingModel`（提供 `encode` 和 `batch_encode`）：

- `test_encode_single_delegates_to_batch`：单条委托
- `test_encode_batch_splits_into_batches`：超 BATCH_SIZE 分批
- `test_encode_batch_transient_retry`：瞬态错误重试成功
- `test_encode_batch_non_transient_raises`：非瞬态直接抛出
- `test_encode_batch_fallback_no_batch_method`：无 `batch_encode` 时逐条调用

- [ ] **步骤 3：实现 embedding_client.py**

- [ ] **步骤 4：运行测试**

```bash
uv run pytest tests/test_embedding_client.py -v
```

- [ ] **步骤 5：lint + type check**

- [ ] **步骤 6：commit**

```
refactor: true batch embedding with retry
```

---

### 任务 5：llm.py 微调

**文件：**
- 微调：`app/memory/memory_bank/llm.py`
- 测试：`tests/stores/test_llm.py`（现有，验证不破坏）

- [ ] **步骤 1：审查现有 llm.py**

现有实现已足够干净。仅需确保：
- 无未使用导入
- 无与已删除模块的依赖

如有小调整直接修改。

- [ ] **步骤 2：运行现有测试**

```bash
uv run pytest tests/stores/test_llm.py -v
```

预期：PASS。

- [ ] **步骤 3：commit（如有变更）**

```
chore: clean up llm.py unused imports
```

---

### 任务 6：summarizer.py 修复重写

**文件：**
- 重写：`app/memory/memory_bank/summarizer.py`
- 测试：`tests/stores/test_summarizer.py`

- [ ] **步骤 1：编写 summarizer.py 接口骨架**

```python
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .faiss_index import FaissIndex
    from .llm import LlmClient

logger = logging.getLogger(__name__)

GENERATION_EMPTY = "GENERATION_EMPTY"

_SYSTEM_PROMPT = (
    "You are an in-car AI assistant with expertise in remembering "
    "vehicle preferences, driving habits, and in-car conversation context."
)

class Summarizer:
    def __init__(self, llm: LlmClient, index: FaissIndex) -> None: ...

    async def generate_daily_summary(self, user_id: str, date_key: str) -> str | None: ...
    async def generate_overall_summary(self, user_id: str) -> str | None: ...
    async def generate_daily_personality(self, user_id: str, date_key: str) -> str | None: ...
    async def generate_overall_personality(self, user_id: str) -> str | None: ...
```

实现思路：
- 从 `retrieval.py` 导入 `_strip_source_prefix`
- `generate_daily_summary` 收集文本时调 `_strip_source_prefix` 清理前缀
- 所有方法加 `user_id` 参数，调 `self._index.get_metadata(user_id)` / `self._index.get_extra(user_id)`
- prompt 模板保持不变（`_summarize_prompt` / `_personality_prompt`）
- 已存在检查：summary → `source == f"summary_{date_key}"`；overall → `extra.get("overall_summary")`
- 空结果写 `GENERATION_EMPTY` 哨兵

- [ ] **步骤 2：编写 test_summarizer.py**

Mock `LlmClient`（`call` 方法返回预设文本）和 `FaissIndex`（`get_metadata` / `get_extra` 返回固定数据）：

- `test_generate_daily_summary_strips_prefix`：输入含前缀，prompt 不含前缀
- `test_generate_daily_summary_already_exists`：已有摘要返回 None
- `test_generate_daily_summary_no_texts`：无该日期文本返回 None
- `test_generate_overall_summary_already_exists`：已有返回 None
- `test_generate_overall_summary_empty_result`：LLM 返回空写 GENERATION_EMPTY
- `test_generate_daily_personality_already_exists`：已有返回 None
- `test_generate_overall_personality_no_dailies`：无日常人格返回 None

- [ ] **步骤 3：实现 summarizer.py**

- [ ] **步骤 4：运行测试**

```bash
uv run pytest tests/stores/test_summarizer.py -v
```

- [ ] **步骤 5：lint + type check**

- [ ] **步骤 6：commit**

```
fix: summarizer prefix stripping + multi-user support
```

---

### 任务 7：store.py 编排层重写

**文件：**
- 重写：`app/memory/memory_bank/store.py`
- 测试：`tests/stores/test_memory_bank_store.py`

- [ ] **步骤 1：编写 store.py 接口骨架**

```python
import asyncio
import contextlib
import logging
import os
import random
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.memory.components import FeedbackManager
from app.memory.embedding_client import EmbeddingClient
from app.memory.schemas import (
    FeedbackData, InteractionResult, MemoryEvent, SearchResult,
)
from .faiss_index import FaissIndex
from .forget import ForgetMode, compute_forget_ids, compute_reference_date
from .llm import LlmClient
from .retrieval import (
    apply_speaker_filter, clean_search_result, deduplicate_overlaps,
    get_effective_chunk_size, merge_neighbors, update_memory_strengths,
)
from .summarizer import GENERATION_EMPTY, Summarizer

if TYPE_CHECKING:
    from pathlib import Path
    from app.models.chat import ChatModel
    from app.models.embedding import EmbeddingModel

class MemoryBankStore:
    store_name = "memory_bank"
    requires_embedding = True
    requires_chat = True
    supports_interaction = True

    def __init__(self, data_dir: Path, embedding_model=None, chat_model=None, **kwargs): ...
    async def _ensure_loaded(self) -> None: ...
    async def write(self, event: MemoryEvent, *, user_id: str = "default") -> str: ...
    async def write_interaction(self, query, response, event_type="reminder",
                                *, user_id="default", **kwargs) -> InteractionResult: ...
    async def search(self, query: str, top_k: int = 10, *, user_id: str = "default") -> list[SearchResult]: ...
    async def get_history(self, limit: int = 10, *, user_id: str = "default") -> list[MemoryEvent]: ...
    async def update_feedback(self, event_id: str, feedback: FeedbackData, *, user_id: str = "default") -> None: ...
    async def get_event_type(self, event_id: str, *, user_id: str = "default") -> str | None: ...
    async def _background_summarize(self, user_id: str, date_key: str) -> None: ...
```

实现思路（write_interaction 流程）：
1. `_ensure_loaded()`
2. 构造对话文本 `f"Conversation content on {date_key}:[|{user_name}|]: {query}; [|{ai_name}|]: {response}"`
3. `self._embedding.encode(text)` 获取向量
4. `self._index.add_vector(user_id, text, emb, ts, {...})` 写入
5. 若遗忘启用：`compute_forget_ids` → `index.remove_vectors` → `index.save`
6. `index.save(user_id)`
7. 若有 summarizer：`asyncio.create_task(_background_summarize(user_id, date_key))`
8. 返回 `InteractionResult(event_id=str(fid))`

实现思路（search 流程）：
1. `_ensure_loaded()`
2. 若遗忘启用：`compute_forget_ids` → `index.remove_vectors` → `index.save`
3. `self._embedding.encode(query)` 获取查询向量
4. `index.search(user_id, emb, top_k * 4)` FAISS 粗排
5. `merge_neighbors` → `deduplicate_overlaps` → `apply_speaker_filter` → 截断 top_k
6. `update_memory_strengths` → 若有修改 `index.save`
7. `clean_search_result`
8. 前置 overall_context（从 `index.get_extra(user_id)` 取 overall_summary/overall_personality）
9. 返回 `list[SearchResult]`

- [ ] **步骤 2：编写 test_memory_bank_store.py**

使用 `tmp_path` + mock embedding（返回固定向量）+ mock LLM：

- `test_write_interaction_and_search`：写入后搜索能找回
- `test_multi_user_isolation`：用户 A 写入不影响用户 B 搜索
- `test_search_returns_overall_context`：有 overall_summary 时前置
- `test_forgetting_enabled_removes_old`：遗忘启用时旧条目被删除
- `test_get_history_excludes_summaries`：daily_summary 不出现在历史中
- `test_update_feedback_records`：反馈被记录
- `test_get_event_type_found`：按 ID 查找事件类型
- `test_get_event_type_not_found`：不存在的 ID 返回 None

- [ ] **步骤 3：实现 store.py**

- [ ] **步骤 4：运行测试**

```bash
uv run pytest tests/stores/test_memory_bank_store.py -v
```

- [ ] **步骤 5：lint + type check**

- [ ] **步骤 6：commit**

```
refactor: rewrite MemoryBankStore with multi-user orchestration
```

---

### 任务 8：interfaces.py + memory.py 更新

**文件：**
- 修改：`app/memory/interfaces.py`
- 修改：`app/memory/memory.py`

- [ ] **步骤 1：更新 interfaces.py**

所有方法签名加 `user_id: str = "default"` keyword-only 参数。保持现有导入和 `MemoryStore` Protocol 结构。

- [ ] **步骤 2：更新 memory.py**

`MemoryModule` 所有方法透传 `user_id`：

```python
async def write(self, event: MemoryEvent, *, mode: MemoryMode | None = None,
                user_id: str = "default") -> str:
    store = await self._get_store(self._resolve_mode(mode))
    return await store.write(event, user_id=user_id)
```

同理更新 `search`、`get_history`、`write_interaction`、`update_feedback`、`get_event_type`。

`_create_store` 方法保持不变（MemoryBankStore 构造函数签名兼容）。

- [ ] **步骤 3：运行受影响测试**

```bash
uv run pytest tests/test_memory_module_facade.py tests/test_memory_store_contract.py -v
```

这些测试可能因接口变更而失败。如失败，在下一步修复。

- [ ] **步骤 4：lint + type check**

- [ ] **步骤 5：commit**

```
feat: add user_id parameter to MemoryStore Protocol and MemoryModule
```

---

### 任务 9：外部消费者更新

**文件：**
- 修改：`app/agents/workflow.py`
- 修改：`app/api/resolvers/query.py`
- 修改：`app/api/resolvers/mutation.py`

- [ ] **步骤 1：更新 workflow.py**

`_context_node` 中 `search` 和 `get_history` 调用加 `user_id="default"`（当前单用户场景）：

```python
related_events = await self.memory_module.search(
    user_input, mode=self._memory_mode, user_id="default"
)
```

`_execution_node` 中 `write_interaction` 调用加 `user_id="default"`。

- [ ] **步骤 2：更新 query.py**

`history` 方法调用 `get_history` 加 `user_id="default"`。

- [ ] **步骤 3：更新 mutation.py**

`submit_feedback` 中 `get_event_type` 和 `update_feedback` 调用加 `user_id="default"`。

- [ ] **步骤 4：运行相关测试**

```bash
uv run pytest tests/test_graphql.py tests/test_embedding.py -v
```

- [ ] **步骤 5：lint + type check**

- [ ] **步骤 6：commit**

```
feat: pass user_id through workflow and API resolvers
```

---

### 任务 10：清理删除

**文件：**
- 删除：`app/memory/utils.py`
- 删除：`app/memory/stores/__init__.py`
- 修改：`app/memory/components.py`（删除 `KeywordSearch`）
- 修改：`app/memory/__init__.py`（更新导出，移除 `stores` 引用）
- 删除：`tests/test_cosine_similarity.py`

- [ ] **步骤 1：删除 utils.py**

```bash
git rm app/memory/utils.py
```

- [ ] **步骤 2：删除 stores/__init__.py**

```bash
git rm app/memory/stores/__init__.py && rmdir app/memory/stores
```

- [ ] **步骤 3：修改 components.py**

删除 `KeywordSearch` 类（第 17-34 行）。保留 `FeedbackManager`。

- [ ] **步骤 4：修改 __init__.py**

移除 `stores` 相关导出。导出清单保持：

```python
from app.memory.memory import MemoryModule, register_store
from app.memory.schemas import (
    FeedbackData, InteractionRecord, InteractionResult,
    MemoryEvent, SearchResult,
)
```

- [ ] **步骤 5：删除 test_cosine_similarity.py**

```bash
git rm tests/test_cosine_similarity.py
```

- [ ] **步骤 6：运行全量 lint + type check**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```

- [ ] **步骤 7：运行全量测试**

```bash
uv run pytest
```

修复因删除导致的导入错误。

- [ ] **步骤 8：commit**

```
chore: remove unused utils.py, KeywordSearch, stores dir
```

---

### 任务 11：测试文件全面更新

**文件：**
- 重写：`tests/stores/test_retrieval.py`
- 重写：`tests/stores/test_forget.py`
- 重写：`tests/stores/test_faiss_index.py`
- 重写：`tests/stores/test_summarizer.py`
- 重写：`tests/stores/test_memory_bank_store.py`
- 重写：`tests/test_embedding_client.py`
- 更新：`tests/test_memory_module_facade.py`
- 更新：`tests/test_memory_store_contract.py`
- 更新：`tests/test_memory_bank.py`
- 更新：`tests/test_components.py`
- 更新：`tests/test_embedding.py`
- 更新：`tests/test_storage.py`

说明：任务 1-7 中已编写各模块对应的新测试。此任务处理剩余旧测试文件的更新——适配新接口（`user_id` 参数、删除 `KeywordSearch` 引用、删除 `utils.py` 引用）。

- [ ] **步骤 1：更新 test_components.py**

删除 `KeywordSearch` 相关测试。保留 `FeedbackManager` 测试。

- [ ] **步骤 2：更新 test_memory_module_facade.py**

所有 `mm.write(...)` / `mm.search(...)` 等调用加 `user_id="default"`。

- [ ] **步骤 3：更新 test_memory_store_contract.py**

同上，加 `user_id="default"`。

- [ ] **步骤 4：更新 test_memory_bank.py**

适配 `MemoryBankStore` 新接口（构造函数参数可能变化，加 `user_id`）。

- [ ] **步骤 5：更新 test_embedding.py 和 test_storage.py**

检查并适配接口变更。

- [ ] **步骤 6：运行全量测试**

```bash
uv run pytest
```

预期：全部 PASS。

- [ ] **步骤 7：lint + type check**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```

- [ ] **步骤 8：commit**

```
test: update all test files for new memory interface
```

---

### 任务 12：最终验证

- [ ] **步骤 1：全量测试**

```bash
uv run pytest
```

- [ ] **步骤 2：lint + type check**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```

- [ ] **步骤 3：确认无残留引用**

```bash
rg "from app.memory.utils" app/ tests/
rg "KeywordSearch" app/ tests/
rg "from app.memory.stores" app/ tests/
```

预期：无匹配。

- [ ] **步骤 4：验证多用户隔离**

手动运行或确认 `test_multi_user_isolation`（test_faiss_index.py 和 test_memory_bank_store.py）通过。
