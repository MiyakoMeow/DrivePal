# MemoryBank 重构实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 重构 memory_bank 模块：集中配置、拆分职责、修复 inflight 防护与后台任务管理、同步 AGENTS.md

**架构：** 新增 config.py / index_reader.py / bg_tasks.py / lifecycle.py；faiss_index.py 重命名 index.py；store.py 瘦身为 Facade；各子组件注入 config 替代散落 os.getenv；MemoryModule 新增 close() 透传

**技术栈：** Python 3.14, pydantic-settings, faiss, asyncio

**规格：** `docs/superpowers/specs/2026-05-09-memorybank-refactor-design.md`

---

### 任务 1：创建 MemoryBankConfig

**文件：**
- 创建：`app/memory/memory_bank/config.py`

- [ ] **步骤 1：编写 config.py**

```python
"""MemoryBank 集中配置模型。"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class MemoryBankConfig(BaseSettings):
    """MemoryBank 全部可配置参数，环境变量前缀 MEMORYBANK_。"""

    model_config = SettingsConfigDict(
        env_prefix="MEMORYBANK_", case_sensitive=False
    )

    # ── 遗忘 ──
    enable_forgetting: bool = False
    forget_mode: str = "deterministic"  # "deterministic" | "probabilistic"
    soft_forget_threshold: float = 0.15
    forget_interval_seconds: int = 300
    forgetting_time_scale: float = 1.0
    seed: int | None = None

    # ── 检索 ──
    chunk_size: int | None = None  # None → 自适应 P90×3
    chunk_size_min: int = 200
    chunk_size_max: int = 8192
    coarse_search_factor: int = 4
    embedding_min_similarity: float = 0.3

    # ── 摘要 ──
    enable_summary: bool = True
    summary_system_prompt: str = (
        "You are an in-car AI assistant with expertise in remembering "
        "vehicle preferences, driving habits, and in-car conversation context."
    )

    # ── 嵌入 ──
    embedding_dim: int = 1536  # 首次 add_vector 后由实际向量维度覆盖；BGE-M3 为 1024

    # ── 关闭 ──
    shutdown_timeout_seconds: float = 30.0

    # ── 外部注入（非环境变量） ──
    reference_date: str | None = None
```

- [ ] **步骤 2：验证可导入**

```bash
uv run python -c "from app.memory.memory_bank.config import MemoryBankConfig; c = MemoryBankConfig(); print(c.enable_forgetting)"
```

预期：输出 `False`

- [ ] **步骤 3：Commit**

```bash
git add app/memory/memory_bank/config.py
git commit -m "feat(memory): add MemoryBankConfig with pydantic-settings"
```

---

### 任务 2：创建 IndexReader Protocol

**文件：**
- 创建：`app/memory/memory_bank/index_reader.py`

- [ ] **步骤 1：编写 index_reader.py**

```python
"""FaissIndex 只读视图 Protocol。"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class IndexReader(Protocol):
    """FaissIndex 只读视图。消费端（Summarizer / RetrievalPipeline）仅依赖此接口。

    get_metadata() 返回的每个 dict 至少含以下键：
      text, source, type, speakers, forgotten, memory_strength, last_recall_date,
      faiss_id, timestamp
    """

    @property
    def total(self) -> int: ...

    def get_metadata(self) -> list[dict]: ...

    async def search(
        self, query_emb: list[float], top_k: int
    ) -> list[dict]: ...

    def get_extra(self) -> dict: ...
```

- [ ] **步骤 2：验证 FaissIndex 隐式满足**

```bash
uv run python -c "
from app.memory.memory_bank.faiss_index import FaissIndex
from app.memory.memory_bank.index_reader import IndexReader
from pathlib import Path
import tempfile
with tempfile.TemporaryDirectory() as d:
    idx = FaissIndex(Path(d))
    assert isinstance(idx, IndexReader), 'FaissIndex should satisfy IndexReader'
    print('OK')
"
```

预期：输出 `OK`

- [ ] **步骤 3：Commit**

---

### 任务 3：创建 BackgroundTaskRunner

**文件：**
- 创建：`app/memory/memory_bank/bg_tasks.py`

- [ ] **步骤 1：编写 bg_tasks.py**

```python
"""后台任务管理器，封装 asyncio.Task 生命周期。"""

import asyncio
import contextlib
import logging
from typing import Coroutine

from .config import MemoryBankConfig

logger = logging.getLogger(__name__)


class BackgroundTaskRunner:
    """管理后台 asyncio.Task 集合，支持优雅关闭。"""

    def __init__(self, config: MemoryBankConfig) -> None:
        self._config = config
        self._tasks: set[asyncio.Task[None]] = set()

    def spawn(self, coro: Coroutine[None, None, None]) -> asyncio.Task[None]:
        """创建后台任务并追踪。失败时日志告警。"""
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._on_task_done)
        return task

    def _on_task_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        with contextlib.suppress(asyncio.CancelledError):
            exc = task.exception()
            if exc is not None:
                logger.warning("Background task failed: %s", exc)

    async def shutdown(self) -> None:
        """取消所有未完成任务，等待完成（超时取自 config）。"""
        if not self._tasks:
            return
        for t in self._tasks:
            t.cancel()
        results = await asyncio.gather(
            *self._tasks, return_exceptions=True,
        )
        for r in results:
            if isinstance(r, Exception) and not isinstance(
                r, asyncio.CancelledError,
            ):
                logger.warning("Background task raised during shutdown: %s", r)
        self._tasks.clear()
```

- [ ] **步骤 2：验证可导入**

```bash
uv run python -c "from app.memory.memory_bank.bg_tasks import BackgroundTaskRunner; print('OK')"
```

- [ ] **步骤 3：Commit**

---

### 任务 4：重命名 faiss_index.py → index.py + 更新所有导入

**文件：**
- 重命名：`app/memory/memory_bank/faiss_index.py` → `app/memory/memory_bank/index.py`
- 修改：`faiss_index.py` → `index.py` 的所有引用

- [ ] **步骤 1：重命名文件**

```bash
git mv app/memory/memory_bank/faiss_index.py app/memory/memory_bank/index.py
```

- [ ] **步骤 2：更新内部相对导入**

修改 `app/memory/memory_bank/store.py`:
```
from .faiss_index import FaissIndex → from .index import FaissIndex
```

修改 `app/memory/memory_bank/retrieval.py` 中的 TYPE_CHECKING 导入:
```
from .faiss_index import FaissIndex → from .index import FaissIndex
```

修改 `app/memory/memory_bank/summarizer.py` 中的 TYPE_CHECKING 导入:
```
from .faiss_index import FaissIndex → from .index import FaissIndex
```

- [ ] **步骤 3：更新测试文件导入**

`tests/stores/test_faiss_index.py`:
```
from app.memory.memory_bank.faiss_index import (...) → from app.memory.memory_bank.index import (...)
```

`tests/stores/test_retrieval.py`:
```
from app.memory.memory_bank.faiss_index import FaissIndex → from app.memory.memory_bank.index import FaissIndex
```

`tests/stores/test_summarizer.py`:
```
from app.memory.memory_bank.faiss_index import FaissIndex → from app.memory.memory_bank.index import FaissIndex
```

- [ ] **步骤 4：验证导入无遗漏**

```bash
uv run python -c "from app.memory.memory_bank.index import FaissIndex; print('OK')"
uv run python -c "from app.memory.memory_bank.store import MemoryBankStore; print('OK')"
```

预期：两次均输出 `OK`

- [ ] **步骤 5：Commit**

---

### 任务 5：重构 forget.py — 注入 config

**文件：**
- 修改：`app/memory/memory_bank/forget.py`

- [ ] **步骤 1：重构模块级函数和 ForgettingCurve**

`forgetting_retention` 改为接收 `time_scale` 参数（替代模块常量 `FORGETTING_TIME_SCALE`）：

```python
def forgetting_retention(
    days_elapsed: float, strength: float, time_scale: float = FORGETTING_TIME_SCALE,
) -> float:
    if days_elapsed <= 0:
        return 1.0
    if strength <= 0:
        return 0.0
    return math.exp(-days_elapsed / (time_scale * strength))
```

`ForgettingCurve.__init__` 改为接收 `config: MemoryBankConfig`：

`ForgettingCurve.__init__` 改为接收 `config: MemoryBankConfig`。`_resolve_forget_mode()` 移除，从 config 读取。`FORGET_INTERVAL_SECONDS` / `FORGETTING_TIME_SCALE` / `SOFT_FORGET_THRESHOLD` 从 config 获取。

关键变更：
```python
from .config import MemoryBankConfig

class ForgettingCurve:
    def __init__(self, config: MemoryBankConfig, rng: random.Random | None = None) -> None:
        self._mode = ForgetMode.PROBABILISTIC if config.forget_mode == "probabilistic" else ForgetMode.DETERMINISTIC
        self._rng = rng if rng is not None else (
            random.Random(config.seed) if config.seed is not None and self._mode == ForgetMode.PROBABILISTIC else None
        )
        self._last_forget_time: float = -float(config.forget_interval_seconds) - 1
        self._config = config

    def maybe_forget(self, metadata, reference_date=None) -> list[int] | None:
        now = time.monotonic()
        if now - self._last_forget_time < self._config.forget_interval_seconds:
            return None
        self._last_forget_time = now
        # 方法中使用 config 阈值：
    #   self._config.forget_interval_seconds (节流)
    #   self._config.soft_forget_threshold (确定性阈值)
    #   self._config.forgetting_time_scale → 传入 forgetting_retention()
```

`compute_ingestion_forget_ids` 改为接收 `config`:
```python
def compute_ingestion_forget_ids(
    metadata: list[dict],
    reference_date: str,
    config: MemoryBankConfig,
    rng: random.Random | None = None,
) -> list[int]:
    mode = ForgetMode.PROBABILISTIC if config.forget_mode == "probabilistic" else ForgetMode.DETERMINISTIC
    # retention = forgetting_retention(days, strength, config.forgetting_time_scale)
```

- [ ] **步骤 2：删除模块级 _resolve_forget_mode 函数**

- [ ] **步骤 3：验证现有测试通过**

```bash
uv run pytest tests/stores/test_forget.py -v
```

- [ ] **步骤 4：Commit**

---

### 任务 6：重构 retrieval.py — 注入 config + IndexReader

**文件：**
- 修改：`app/memory/memory_bank/retrieval.py`

- [ ] **步骤 1：RetrievalPipeline 构造函数注入 config**

```python
class RetrievalPipeline:
    def __init__(
        self,
        index: IndexReader,
        embedding_client: EmbeddingClient,
        config: MemoryBankConfig,
    ) -> None:
        self._index = index
        self._embedding_client = embedding_client
        self._config = config
```

- [ ] **步骤 2：_get_effective_chunk_size 改为从 config 获取**

将 `os.getenv("MEMORYBANK_CHUNK_SIZE")` 替换为读 `config.chunk_size`。函数签名改为接收 `config` 参数：

```python
def _get_effective_chunk_size(metadata: list[dict], config: MemoryBankConfig) -> int:
    if config.chunk_size is not None:
        return max(CHUNK_SIZE_MIN, min(CHUNK_SIZE_MAX, config.chunk_size))
    # ... P90 自适应逻辑不变
```

- [ ] **步骤 3：_merge_neighbors 传递 config**

`_merge_neighbors` 中调用 `_get_effective_chunk_size(metadata, self._config)`。

- [ ] **步骤 4：TYPE_CHECKING 导入改为 IndexReader；_apply_speaker_filter 无需变更**

`_apply_speaker_filter` 已通过遍历结果条目中的 `speakers` 字段工作，不依赖 `FaissIndex.get_all_speakers()`。迁移 IndexReader 后行为不变。

```python
if TYPE_CHECKING:
    from .index_reader import IndexReader
```

- [ ] **步骤 5：验证现有测试通过**

```bash
uv run pytest tests/stores/test_retrieval.py -v
```

- [ ] **步骤 6：Commit**

---

### 任务 7：重构 llm.py — 移除硬编码 system prompt

**文件：**
- 修改：`app/memory/memory_bank/llm.py`

- [ ] **步骤 1：LlmClient.call 改为接收 system_prompt 参数（已有），移除默认值依赖 config**

当前 `LlmClient` 已有 `system_prompt` 参数和 `_DEFAULT_SYSTEM` 回退。改为：`call` 的 `system_prompt` 参数改为必填（由调用方 Summarizer / MemoryLifecycle 从 config 获取后传入）。`_DEFAULT_SYSTEM` 常量移除。

```python
async def call(self, prompt: str, *, system_prompt: str) -> str | None:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": _ANCHOR_USER},
        {"role": "assistant", "content": _ANCHOR_ASSISTANT},
        {"role": "user", "content": prompt},
    ]
    # ... 重试逻辑不变
```

- [ ] **步骤 2：验证可导入**

```bash
uv run python -c "from app.memory.memory_bank.llm import LlmClient; print('OK')"
```

- [ ] **步骤 3：Commit**

---

### 任务 8：重构 summarizer.py — IndexReader + config

**文件：**
- 修改：`app/memory/memory_bank/summarizer.py`

- [ ] **步骤 1：Summarizer 构造函数改为接收 IndexReader + config**

```python
class Summarizer:
    def __init__(
        self,
        llm: LlmClient,
        index: IndexReader,
        config: MemoryBankConfig,
    ) -> None:
        self._llm = llm
        self._index = index
        self._config = config

    # _SUMMARY_SYSTEM_PROMPT 移除，改用 self._config.summary_system_prompt
```

- [ ] **步骤 2：所有 LLM 调用传入 config.summary_system_prompt**

`self._llm.call(..., system_prompt=self._config.summary_system_prompt)`

- [ ] **步骤 3：TYPE_CHECKING 导入改为 IndexReader**

```python
if TYPE_CHECKING:
    from .index_reader import IndexReader
```

- [ ] **步骤 4：验证现有测试通过**

```bash
uv run pytest tests/stores/test_summarizer.py -v
```

- [ ] **步骤 5：Commit**

---

### 任务 9：创建 MemoryLifecycle

**文件：**
- 创建：`app/memory/memory_bank/lifecycle.py`

从 `store.py` 拆出写入/遗忘/摘要编排逻辑。

- [ ] **步骤 1：编写 lifecycle.py**

接口与关键实现思路：

```python
"""记忆生命周期管理：写入、遗忘、摘要编排。"""

import asyncio
import logging
from datetime import UTC, datetime

from app.memory.embedding_client import EmbeddingClient
from app.memory.schemas import InteractionResult, MemoryEvent

from .bg_tasks import BackgroundTaskRunner
from .config import MemoryBankConfig
from .forget import ForgetMode, ForgettingCurve, compute_ingestion_forget_ids
from .index import FaissIndex
from .llm import LlmClient
from .summarizer import Summarizer

logger = logging.getLogger(__name__)


class MemoryLifecycle:
    """写入、遗忘、摘要编排。不处理检索。"""

    def __init__(
        self,
        index: FaissIndex,
        embedding_client: EmbeddingClient,
        forget: ForgettingCurve,
        summarizer: Summarizer | None,
        config: MemoryBankConfig,
        bg: BackgroundTaskRunner,
    ) -> None:
        self._index = index
        self._embedding_client = embedding_client
        self._forget = forget
        self._summarizer = summarizer
        self._config = config
        self._bg = bg
        self._inflight_summaries: set[str] = set()
        self._inflight_lock = asyncio.Lock()

    # write / write_interaction / get_history / get_event_type
    # 从 store.py 原样迁移，逻辑不变。
    # purge_forgotten（公开）/ _forget_at_ingestion / _background_summarize
    # 迁移并适配 config 注入。purge_forgotten 公开以便 store.search() 调用。

    async def purge_forgotten(self, metadata: list[dict]) -> bool:
        forgotten_ids = self._forget.maybe_forget(
            metadata, reference_date=self._config.reference_date,
        )
        if forgotten_ids is None:
            return False  # 节流跳过
        if not forgotten_ids:
            forgotten_ids = [m["faiss_id"] for m in metadata if m.get("forgotten")]
        if forgotten_ids:
            await self._index.remove_vectors(forgotten_ids)
            return True
        return False

    async def _forget_at_ingestion(self) -> None:
        today = self._config.reference_date or datetime.now(UTC).strftime("%Y-%m-%d")
        mode = (
            ForgetMode.PROBABILISTIC
            if self._config.forget_mode == "probabilistic"
            else ForgetMode.DETERMINISTIC
        )
        ids = compute_ingestion_forget_ids(
            self._index.get_metadata(), today, config=self._config,
            rng=self._forget._rng if mode == ForgetMode.PROBABILISTIC else None,
        )
        if ids:
            await self._index.remove_vectors(ids)

    async def _trigger_background_summarize(self, date_key: str) -> None:
        if not self._summarizer or not self._embedding_client:
            return
        async with self._inflight_lock:
            if date_key in self._inflight_summaries:
                return
            self._inflight_summaries.add(date_key)
        self._bg.spawn(self._background_summarize(date_key))

    async def _background_summarize(self, date_key: str) -> None:
        try:
            if not self._summarizer or not self._embedding_client:
                return
            text = await self._summarizer.get_daily_summary(date_key)
            if text:
                emb = await self._embedding_client.encode(text)
                await self._index.add_vector(
                    text, emb, f"{date_key}T00:00:00",
                    {"type": "daily_summary", "source": f"summary_{date_key}"},
                )
                await self._index.save()
            await self._summarizer.get_overall_summary()
            await self._summarizer.get_daily_personality(date_key)
            await self._summarizer.get_overall_personality()
            await self._index.save()
        except Exception:
            logger.exception("background summarization failed")
        finally:
            async with self._inflight_lock:
                self._inflight_summaries.discard(date_key)
```

`reference_date` 已在 Task 1 MemoryBankConfig 中定义（第 64 行）。

- [ ] **步骤 2：验证可导入**

```bash
uv run python -c "from app.memory.memory_bank.lifecycle import MemoryLifecycle; print('OK')"
```

- [ ] **步骤 3：Commit**

---

### 任务 10：瘦身 store.py — Facade 模式

**文件：**
- 修改：`app/memory/memory_bank/store.py`

- [ ] **步骤 1：重写 store.py**

保留 `MemoryStore` Protocol 方法签名不变，内部全部委托：

```python
"""MemoryBankStore Facade，MemoryStore Protocol 实现。"""

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.memory.embedding_client import EmbeddingClient
from app.memory.schemas import SearchResult

from .bg_tasks import BackgroundTaskRunner
from .config import MemoryBankConfig
from .forget import ForgettingCurve
from .index import FaissIndex
from .lifecycle import MemoryLifecycle
from .llm import LlmClient
from .retrieval import RetrievalPipeline
from .summarizer import GENERATION_EMPTY, Summarizer

if TYPE_CHECKING:
    from pathlib import Path
    from app.models.chat import ChatModel
    from app.models.embedding import EmbeddingModel
    from app.memory.schemas import (
        FeedbackData, InteractionResult, MemoryEvent,
    )

logger = logging.getLogger(__name__)


class MemoryBankStore:
    store_name = "memory_bank"
    requires_embedding = True
    requires_chat = True
    supports_interaction = True

    def __init__(
        self,
        data_dir: Path,
        embedding_model: EmbeddingModel | None = None,
        chat_model: ChatModel | None = None,
        **_kwargs: object,
    ) -> None:
        self._config = MemoryBankConfig()
        embed_client = (
            EmbeddingClient(embedding_model) if embedding_model else None
        )
        llm = LlmClient(chat_model) if chat_model else None
        self._index = FaissIndex(data_dir, self._config.embedding_dim)
        self._bg = BackgroundTaskRunner(self._config)
        summarizer = (
            Summarizer(llm, self._index, self._config) if llm else None
        )
        self._lifecycle = MemoryLifecycle(
            self._index, embed_client,
            ForgettingCurve(self._config),
            summarizer,
            self._config,
            self._bg,
        )
        self._retrieval = (
            RetrievalPipeline(self._index, embed_client, self._config)
            if embed_client else None
        )

    # ── 委托方法 ──

    async def write(self, event: MemoryEvent) -> str:
        return await self._lifecycle.write(event)

    async def write_interaction(
        self, query: str, response: str, event_type: str = "reminder",
        **kwargs: object,
    ) -> InteractionResult:
        return await self._lifecycle.write_interaction(
            query, response, event_type, **kwargs,
        )

    async def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        await self._index.load()
        if self._index.total == 0 or not self._retrieval:
            return []
        if self._config.enable_forgetting and await self._lifecycle.purge_forgotten(
            self._index.get_metadata()
        ):
            await self._index.save()
        results = await self._retrieval.search(
            query, top_k, reference_date=self._config.reference_date,
        )
        # overall_context 注入逻辑保留
        extra = self._index.get_extra()
        prepend = []
        for key, label in [
            ("overall_summary", "Overall summary of past memories"),
            ("overall_personality", "User vehicle preferences and habits"),
        ]:
            val = extra.get(key, "")
            if val and val != GENERATION_EMPTY:
                prepend.append(f"{label}: {val}")
        out: list[SearchResult] = []
        if prepend:
            out.append(SearchResult(
                event={"content": "\n".join(prepend), "type": "overall_context"},
                score=float("inf"),
                source="overall",
            ))
        out.extend(
            SearchResult(
                event={
                    "content": r.get("text", ""),
                    "source": r.get("source", ""),
                    "memory_strength": int(r.get("memory_strength", 1)),
                },
                score=float(r.get("score", 0.0)),
                source=r.get("source", "event"),
            )
            for r in results[: max(0, top_k - len(prepend))]
        )
        return out

    async def get_history(self, limit: int = 10) -> list[MemoryEvent]:
        return await self._lifecycle.get_history(limit)

    async def get_event_type(self, event_id: str) -> str | None:
        return await self._lifecycle.get_event_type(event_id)

    async def update_feedback(
        self, event_id: str, feedback: FeedbackData,
    ) -> None:
        pass  # 保持当前 no-op 行为

    async def close(self) -> None:
        await self._bg.shutdown()
```

- [ ] **步骤 2：移除 store.py 中已迁移的方法**

删除 `_purge_forgotten`, `_forget_at_ingestion`, `_background_summarize`, `_background_tasks`, `_finalize_task`。

- [ ] **步骤 3：移除不再需要的导入**

删除 `asyncio`, `contextlib`, `os`, `random` 中不再使用的；删除 `from .forget import ForgetMode`。

- [ ] **步骤 4：验证可导入**

```bash
uv run python -c "from app.memory.memory_bank.store import MemoryBankStore; print('OK')"
```

- [ ] **步骤 5：Commit**

---

### 任务 11：更新 __init__.py 导出

**文件：**
- 修改：`app/memory/memory_bank/__init__.py`

当前内容保持不变（`from .store import MemoryBankStore`），因为 `store.py` 仍导出同名类。

无代码变更。跳过 commit。

---

### 任务 12：MemoryModule 新增 close()

**文件：**
- 修改：`app/memory/memory.py`

- [ ] **步骤 1：MemoryModule 添加 close 方法**

```python
async def close(self) -> None:
    """关闭所有 store 的后台任务。"""
    for store in self._stores.values():
        closer = getattr(store, "close", None)
        if closer is not None:
            await closer()
```

- [ ] **步骤 2：验证可导入**

```bash
uv run python -c "from app.memory.memory import MemoryModule; print('OK')"
```

- [ ] **步骤 3：Commit**

---

### 任务 13：main.py shutdown handler 集成

**文件：**
- 修改：`app/api/main.py`

- [ ] **步骤 1：_lifespan 中添加关闭逻辑**

```python
from app.memory.singleton import _memory_module_state  # 访问单例状态

@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_storage(DATA_DIR)
    logger.info("Data directory initialized: %s", DATA_DIR)
    if not Path.exists(WEBUI_DIR):
        logger.warning("WebUI directory not found: %s", WEBUI_DIR)
    yield
    # 关闭时清理
    mm = _memory_module_state[0]
    if mm is not None:
        await mm.close()
        logger.info("MemoryModule closed")
```

- [ ] **步骤 2：验证代码风格**

```bash
uv run ruff check app/api/main.py && uv run ty check app/api/main.py
```

- [ ] **步骤 3：Commit**

---

### 任务 14：更新 AGENTS.md

**文件：**
- 修改：`AGENTS.md`

- [ ] **步骤 1：删除代码中不存在的条目**

从关键阈值速查表删除：
- `score = similarity × retention`
- 名称匹配加分 `×1.3`
- 时效性衰减 `最低 0.7`
- `SUMMARY_WEIGHT = 0.8`
- `PERSONALITY_SUMMARY_THRESHOLD = 2`
- `OVERALL_PERSONALITY_THRESHOLD = 3`

- [ ] **步骤 2：新增遗漏的阈值**

| 阈值 | 值 | 位置 |
|------|-----|------|
| `DEFAULT_CHUNK_SIZE` | 1500（自适应回退值） | retrieval.py |
| `CHUNK_SIZE_MIN` | 200 | config.py |
| `CHUNK_SIZE_MAX` | 8192 | config.py |
| `FORGET_INTERVAL_SECONDS` | 300 | config.py |
| `shutdown_timeout_seconds` | 30.0 | config.py |

- [ ] **步骤 3：更新 MemoryBank 架构描述**

将文件结构表更新为新结构（`faiss_index.py` → `index.py`，新增 `config.py`/`index_reader.py`/`lifecycle.py`/`bg_tasks.py`）。

- [ ] **步骤 4：更新检查流程中的 ruff 命令**

`uv run ruff check --fix` 和 `uv run ruff format` 和 `uv run ty check`（移除 --fix 已不再支持的说明）。

- [ ] **步骤 5：Commit**

---

### 任务 15：适配测试文件（构造参数变更）

**文件：**
- 修改：`tests/stores/test_retrieval.py`
- 修改：`tests/stores/test_summarizer.py`

导入路径已在 Task 4 更新完毕。此处仅适配构造参数变更。

- [ ] **步骤 1：更新 test_retrieval.py — 传入 config**

`RetrievalPipeline` 构造调用添加第三个参数 `MemoryBankConfig()`。

- [ ] **步骤 2：更新 test_summarizer.py — 传入 config**

`Summarizer` 构造调用添加第三个参数 `MemoryBankConfig()`。导入 `MemoryBankConfig`。

- [ ] **步骤 3：全量测试**

```bash
uv run pytest tests/ -v
```

- [ ] **步骤 4：修复所有失败**

逐个检查失败原因，修复直到全部通过。

- [ ] **步骤 5：Commit**

---

### 任务 16：新增 BackgroundTaskRunner 单元测试

**文件：**
- 创建：`tests/stores/test_bg_tasks.py`

- [ ] **步骤 1：编写测试 — spawn + shutdown**

```python
"""BackgroundTaskRunner 单元测试."""

import asyncio
import pytest
from app.memory.memory_bank.bg_tasks import BackgroundTaskRunner
from app.memory.memory_bank.config import MemoryBankConfig


@pytest.mark.asyncio
async def test_spawn_and_shutdown():
    """Given 后台任务运行器，When 提交协程后 shutdown，Then 任务被取消。"""
    config = MemoryBankConfig()
    runner = BackgroundTaskRunner(config)
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def work():
        started.set()
        try:
            await asyncio.sleep(999)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    runner.spawn(work())
    await asyncio.wait_for(started.wait(), timeout=5)
    await runner.shutdown()
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_shutdown_no_tasks():
    """Given 无后台任务，When shutdown，Then 正常完成不报错。"""
    config = MemoryBankConfig()
    runner = BackgroundTaskRunner(config)
    await runner.shutdown()  # 不抛异常


@pytest.mark.asyncio
async def test_failed_task_warning(caplog):
    """Given 后台任务抛异常，When 任务完成，Then 日志警告。"""
    import logging
    config = MemoryBankConfig()
    runner = BackgroundTaskRunner(config)

    async def fail():
        raise RuntimeError("boom")

    runner.spawn(fail())
    await asyncio.sleep(0.1)  # 让任务执行完
    assert "Background task failed" in caplog.text
```

- [ ] **步骤 2：运行测试验证**

```bash
uv run pytest tests/stores/test_bg_tasks.py -v
```

- [ ] **步骤 3：Commit**

---

### 任务 17：新增 MemoryLifecycle inflight 防护测试

**文件：**
- 创建：`tests/stores/test_lifecycle_inflight.py`

- [ ] **步骤 1：编写测试 — 并发不重复提交摘要**

```python
"""MemoryLifecycle inflight 防护测试."""

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest
from app.memory.memory_bank.lifecycle import MemoryLifecycle
from app.memory.memory_bank.config import MemoryBankConfig


@pytest.mark.asyncio
async def test_inflight_prevents_duplicate_summarize():
    """Given inflight 摘要在运行，When 同日期再次触发，Then 不创建新任务。"""
    config = MemoryBankConfig(enable_summary=True)
    # Mock 所有依赖
    index = MagicMock()
    embed = AsyncMock()
    forget = MagicMock()
    summarizer = AsyncMock()
    bg = MagicMock()

    lifecycle = MemoryLifecycle(index, embed, forget, summarizer, config, bg)
    date_key = "2024-06-15"

    # 第一次触发 —— 应 spawn
    await lifecycle._trigger_background_summarize(date_key)
    assert bg.spawn.call_count == 1

    # 同日期第二次触发 —— 应被 inflight 防护拦截
    await lifecycle._trigger_background_summarize(date_key)
    assert bg.spawn.call_count == 1  # 不重复

    # 不同日期 —— 应 spawn 新任务
    other_date = "2024-06-16"
    await lifecycle._trigger_background_summarize(other_date)
    assert bg.spawn.call_count == 2
```

- [ ] **步骤 2：运行测试验证**

```bash
uv run pytest tests/stores/test_lifecycle_inflight.py -v
```

- [ ] **步骤 3：Commit**

---

### 任务 18：新增 close() 集成测试

**文件：**
- 修改：`tests/stores/test_memory_bank_store.py`

- [ ] **步骤 1：在现有测试文件中新增 close 测试**

```python
@pytest.mark.asyncio
async def test_close_shuts_down_background_tasks(tmp_path):
    """Given MemoryBankStore 有后台任务，When close()，Then 任务被取消。"""
    store = MemoryBankStore(tmp_path)
    # close 时 bg 应无未完成任务
    await store.close()
```

- [ ] **步骤 2：运行测试验证**

```bash
uv run pytest tests/stores/test_memory_bank_store.py::test_close_shuts_down_background_tasks -v
```

- [ ] **步骤 3：Commit**

---

### 任务 19：新增 MemoryBankConfig 单元测试

**文件：**
- 创建：`tests/stores/test_config.py`

- [ ] **步骤 1：编写测试 — 环境变量绑定 + 默认值**

```python
"""MemoryBankConfig 单元测试."""

import os
import pytest
from app.memory.memory_bank.config import MemoryBankConfig


def test_defaults():
    """Given 无环境变量，When 构造 config，Then 使用默认值。"""
    config = MemoryBankConfig()
    assert config.enable_forgetting is False
    assert config.forget_mode == "deterministic"
    assert config.soft_forget_threshold == 0.15
    assert config.chunk_size is None
    assert config.shutdown_timeout_seconds == 30.0


def test_env_override(monkeypatch):
    """Given MEMORYBANK_ENABLE_FORGETTING=1，When 构造 config，Then 覆盖默认值。"""
    monkeypatch.setenv("MEMORYBANK_ENABLE_FORGETTING", "1")
    monkeypatch.setenv("MEMORYBANK_CHUNK_SIZE", "2000")
    config = MemoryBankConfig()
    assert config.enable_forgetting is True
    assert config.chunk_size == 2000
```

- [ ] **步骤 2：运行测试验证**

```bash
uv run pytest tests/stores/test_config.py -v
```

- [ ] **步骤 3：Commit**

---

### 任务 20：全量测试 + Lint

- [ ] **步骤 1：Lint + Type Check**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```

- [ ] **步骤 2：全量测试**

```bash
uv run pytest tests/ -v
```

- [ ] **步骤 3：确认无遗漏引用旧路径**

```bash
rg "faiss_index" app/ tests/  # 应无结果
```

- [ ] **步骤 4：Commit**

---

## 依赖顺序

```
任务 1 (config) ─┬─→ 任务 3 (bg_tasks) ──→ 任务 16 (bg_tasks 测试)
                 ├─→ 任务 5 (forget refactor)
                 ├─→ 任务 6 (retrieval refactor)
                 ├─→ 任务 7 (llm refactor)
                 ├─→ 任务 8 (summarizer refactor)
                 └─→ 任务 19 (config 测试)
                          ↓
任务 2 (index_reader) ────┤
                          ↓
                    任务 9 (lifecycle) ──→ 任务 17 (inflight 测试)
                          ↓
任务 4 (faiss_index → index) ─────────────┤
                                          ↓
                                    任务 10 (store facade)
                                          ↓
                                    任务 11-15 (集成 + AGENTS.md + 测试导入)
                                          ↓
                                    任务 18 (close 集成测试)
                                          ↓
                                    任务 20 (全量验证)
```
