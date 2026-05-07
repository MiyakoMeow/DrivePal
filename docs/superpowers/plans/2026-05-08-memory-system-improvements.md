# 记忆系统改进实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 补齐 DrivePal 记忆系统的 5 项缺失功能（P0 + P1），源自 VehicleMemBench 差异分析

**架构：** EmbeddingClient 弹性封装（对标 LlmClient）+ MemoryBankStore 引用日期 + FaissIndex 3 项防御性修复

**技术栈：** Python 3.14, FAISS, pytest, asyncio, openai

---

## 文件结构

### 新文件
- `app/memory/embedding_client.py` — EmbeddingClient 弹性封装
- `tests/test_embedding_client.py` — EmbeddingClient 测试

### 修改文件
- `app/memory/memory_bank/store.py` — 使用 EmbeddingClient + reference_date 参数
- `app/memory/memory_bank/retrieval.py` — 接收 embedding_client 替代 embedding_model
- `app/memory/memory_bank/faiss_index.py` — _next_id 同步 + 维度不匹配异常 + JSON null 防御
- `tests/stores/test_faiss_index.py` — 3 项防御性修复测试
- `tests/stores/test_retrieval.py` — 更新构造参数
- `tests/stores/test_memory_bank_store.py` — 更新构造参数

---

### 任务 1：创建 EmbeddingClient

**文件：**
- 创建：`app/memory/embedding_client.py`
- 创建：`tests/test_embedding_client.py`

- [ ] **步骤 1：编写 EmbeddingClient 测试（encode 重试）**

```python
# tests/test_embedding_client.py
import asyncio
import random

import pytest

from app.memory.embedding_client import EmbeddingClient


class _FakeEmbeddingModel:
    """模拟 EmbeddingModel，可配置失败行为."""

    def __init__(self) -> None:
        self.call_count = 0
        self.fail_count = 0
        self.fail_pattern: str | None = None

    async def encode(self, text: str) -> list[float]:
        self.call_count += 1
        if self.fail_count > 0:
            self.fail_count -= 1
            msg = f"{self.fail_pattern or 'connection'} error"
            raise RuntimeError(msg)
        return [0.1, 0.2, 0.3]

    async def batch_encode(self, texts: list[str]) -> list[list[float]]:
        return [await self.encode(t) for t in texts]


async def test_encode_success_first_try() -> None:
    """encode 首次成功无重试."""
    model = _FakeEmbeddingModel()
    client = EmbeddingClient(model)
    result = await client.encode("hello")
    assert result == [0.1, 0.2, 0.3]
    assert model.call_count == 1


async def test_encode_retry_on_transient_error() -> None:
    """瞬态错误后重试直至成功."""
    model = _FakeEmbeddingModel()
    model.fail_count = 2
    model.fail_pattern = "timeout"
    client = EmbeddingClient(model)
    result = await client.encode("hello")
    assert result == [0.1, 0.2, 0.3]
    assert model.call_count == 3


async def test_encode_retry_exhausted() -> None:
    """重试耗尽后抛出."""
    model = _FakeEmbeddingModel()
    model.fail_count = 10  # > MAX_RETRIES
    model.fail_pattern = "connection"
    client = EmbeddingClient(model)
    with pytest.raises(RuntimeError):
        await client.encode("hello")
    assert model.call_count == EmbeddingClient.MAX_RETRIES


async def test_encode_non_transient_fast_fail() -> None:
    """非瞬态错误不重试."""
    model = _FakeEmbeddingModel()
    model.fail_pattern = "invalid api key"
    # 非瞬态错在首次即抛出，不计入重试
    model.fail_count = 1
    client = EmbeddingClient(model)
    with pytest.raises(RuntimeError):
        await client.encode("hello")
    assert model.call_count == 1  # 仅 1 次


async def test_encode_batch() -> None:
    """encode_batch 委托给 model.batch_encode."""
    model = _FakeEmbeddingModel()
    client = EmbeddingClient(model)
    results = await client.encode_batch(["a", "b"])
    assert len(results) == 2
    assert results[0] == [0.1, 0.2, 0.3]
```

- [ ] **步骤 2：运行测试验证失败**

运行：`uv run pytest tests/test_embedding_client.py -v`
预期：ModuleNotFoundError / ImportError（`embedding_client.py` 不存在）

- [ ] **步骤 3：编写 EmbeddingClient 实现**

注意：`encode_batch` 使用自身重试策略（MAX_RETRIES=5、BATCH_SIZE=100），
而非委托 `model.batch_encode`（后者 BATCH_SIZE=32、重试 3 次）。
分批循环中每条调 `model.encode` 以确保 EmbeddingClient 的完整重试生效。

```python
# app/memory/embedding_client.py
"""弹性 embedding 封装，对标 LlmClient。"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.embedding import EmbeddingModel

logger = logging.getLogger(__name__)

_SLEEP = asyncio.sleep

_TRANSIENT_PATTERNS = (
    "connection",
    "timeout",
    "rate limit",
    "eof",
    "reset",
    "service unavailable",
    "bad gateway",
    "internal server error",
)


class EmbeddingClient:
    """EmbeddingModel 的弹性封装，提供单条编码重试和分批编码。"""

    MAX_RETRIES = 5
    BACKOFF_BASE = 2
    BATCH_SIZE = 100

    def __init__(
        self,
        embedding_model: EmbeddingModel,
        *,
        rng: random.Random | None = None,
    ) -> None:
        """初始化 EmbeddingClient。

        Args:
            embedding_model: 嵌入模型实例。
            rng: 可选 RNG 实例（用于退避 jitter）。

        """
        self._model = embedding_model
        self._rng = rng if rng is not None else random.Random()

    async def encode(self, text: str) -> list[float]:
        """编码单条文本，瞬态错误时指数退避重试。"""
        for attempt in range(self.MAX_RETRIES):
            try:
                return await self._model.encode(text)
            except Exception as exc:
                err = str(exc).lower()
                if any(p in err for p in _TRANSIENT_PATTERNS):
                    if attempt < self.MAX_RETRIES - 1:
                        delay = min(self.BACKOFF_BASE**attempt, 10)
                        delay += self._rng.random() * 0.5
                        await _SLEEP(delay)
                        continue
                raise
        # 防御性 fallback（MAX_RETRIES <= 1 时可达）
        return await self._model.encode(text)

    async def encode_batch(
        self, texts: list[str]
    ) -> list[list[float]]:
        """分批编码，每条走 encode() 以使用统一重试策略。"""
        if not texts:
            return []
        results: list[list[float]] = []
        for i in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[i : i + self.BATCH_SIZE]
            for text in batch:
                vec = await self.encode(text)
                results.append(vec)
        return results
```

- [ ] **步骤 4：运行测试验证通过**

运行：`uv run pytest tests/test_embedding_client.py -v`
预期：4 passed

- [ ] **步骤 5：Commit**

```bash
git add app/memory/embedding_client.py tests/test_embedding_client.py
git commit -m "feat: add EmbeddingClient with retry for embedding calls"
```

---

### 任务 2：RetrievalPipeline + MemoryBankStore 改用 EmbeddingClient

注意：此任务包含 RetrievalPipeline 和 MemoryBankStore 两处改动，
需要在两个文件都修改完成后统一验证，中间状态不 commit。

**文件：**
- 修改：`app/memory/memory_bank/retrieval.py`
- 修改：`app/memory/memory_bank/store.py`
- 修改：`tests/stores/test_retrieval.py`
- 修改：`tests/stores/test_memory_bank_store.py`

- [ ] **步骤 1：修改 RetrievalPipeline 构造**

```python
# app/memory/memory_bank/retrieval.py

class RetrievalPipeline:
    def __init__(
        self,
        index: FaissIndex,
        embedding_client: EmbeddingClient,  # 从 embedding_model 改为 embedding_client
    ) -> None:
        self._index = index
        self._embedding_client = embedding_client

    async def search(self, query: str, top_k: int = 5) -> list[dict]:
        # ...
        query_emb = await self._embedding_client.encode(query)
```

- [ ] **步骤 2：修改 MemoryBankStore 构造 + 方法**

```python
# app/memory/memory_bank/store.py
# 在 __init__ 参数中增加：
#   reference_date: str | None = None,
#   embedding_client: EmbeddingClient | None = None,
# 在构造方法末尾增加：
#   from app.memory.embedding_client import EmbeddingClient
#   self._embedding_client = embedding_client or EmbeddingClient(embedding_model)
#   self._reference_date = reference_date
#   self._retrieval = (
#       RetrievalPipeline(self._index, self._embedding_client)
#       if self._embedding_client
#       else None
#   )
   
# 替换所有 self._embedding_model.encode() → self._embedding_client.encode()

# 引用日期传递：
# _purge_forgotten:
forgotten_ids = self._forget.maybe_forget(metadata, reference_date=self._reference_date)

# _forget_at_ingestion:
today = self._reference_date or datetime.now(UTC).strftime("%Y-%m-%d")
```

- [ ] **步骤 3：更新测试文件中的构造调用**

```python
# test_retrieval.py: RetrievalPipeline(mock_index, mock_model)
# → RetrievalPipeline(mock_index, EmbeddingClient(mock_model))

# test_memory_bank_store.py: MemoryBankStore(data_dir, embedding_model=mock_model)
# → MemoryBankStore(data_dir, embedding_model=mock_model)  # 保持不变，内部会包装
```

- [ ] **步骤 4：运行测试验证**

运行：`uv run pytest tests/stores/test_retrieval.py tests/stores/test_memory_bank_store.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add app/memory/memory_bank/retrieval.py app/memory/memory_bank/store.py tests/stores/test_retrieval.py tests/stores/test_memory_bank_store.py
git commit -m "feat: integrate EmbeddingClient and reference_date into RetrievalPipeline and MemoryBankStore"
```

---

### 任务 3：FaissIndex 三项修复

**文件：**
- 修改：`app/memory/memory_bank/faiss_index.py`
- 修改：`tests/stores/test_faiss_index.py`

- [ ] **步骤 1：编写测试**

```python
# tests/stores/test_faiss_index.py 追加

async def test_remove_vectors_syncs_next_id(tmp_path: Path) -> None:
    """remove_vectors 后 _next_id 正确同步。"""
    from app.memory.memory_bank.faiss_index import FaissIndex

    idx = FaissIndex(tmp_path)
    fid1 = await idx.add_vector("a", [0.1, 0.2, 0.3], "2024-01-01T00:00:00")
    fid2 = await idx.add_vector("b", [0.4, 0.5, 0.6], "2024-01-01T00:00:00")
    assert idx._next_id == 2  # noqa: SLF001  add 后为 2
    await idx.remove_vectors([fid1])
    # 删除后 _next_id 应从剩余最大 ID +1
    assert idx._next_id == fid2 + 1


async def test_add_vector_dim_mismatch_raises(tmp_path: Path) -> None:
    """维度不匹配时抛出 ValueError 而非静默重建。"""
    from app.memory.memory_bank.faiss_index import FaissIndex

    idx = FaissIndex(tmp_path)
    await idx.add_vector("a", [0.1, 0.2, 0.3], "2024-01-01T00:00:00")
    with pytest.raises(ValueError, match="dimension mismatch"):
        await idx.add_vector("b", [0.4, 0.5], "2024-01-01T00:00:00")


async def test_get_extra_null_defense(tmp_path: Path) -> None:
    """get_extra 返回空 dict 而非 None。"""
    from app.memory.memory_bank.faiss_index import FaissIndex

    idx = FaissIndex(tmp_path)
    idx._extra = {"key": "val"}  # noqa: SLF001
    assert idx.get_extra() == {"key": "val"}
    idx._extra = None  # noqa: SLF001
    assert idx.get_extra() == {}


async def test_load_extra_null_defense(tmp_path: Path) -> None:
    """加载损坏的 extra_metadata.json 时回退空 dict。"""
    from app.memory.memory_bank.faiss_index import FaissIndex

    # 先写正常数据，使索引和 metadata 存在
    idx = FaissIndex(tmp_path)
    await idx.add_vector("a", [0.1, 0.2, 0.3], "2024-01-01T00:00:00")
    await idx.save()
    # 写一个 null 的 extra_metadata.json
    (tmp_path / "extra_metadata.json").write_text("null")
    # 重新加载
    idx2 = FaissIndex(tmp_path)
    await idx2.load()
    assert idx2.get_extra() == {}
```

- [ ] **步骤 2：实现三项修复**

```python
# faiss_index.py

# 1. remove_vectors 末尾：
self._next_id = max((m["faiss_id"] for m in self._metadata), default=-1) + 1

# 2. add_vector 中维度不匹配：
elif self._index.d != emb_dim:
    logger.warning(
        "FaissIndex dimension mismatch: index=%d, vector=%d. "
        "Check embedding model consistency.",
        self._index.d,
        emb_dim,
    )
    msg = (
        f"Embedding dimension mismatch: "
        f"index expects {self._index.d}-dim, "
        f"but got {emb_dim}-dim vector. "
        f"Check embedding model settings or rebuild index."
    )
    raise ValueError(msg)

# 3. get_extra():
def get_extra(self) -> dict:
    return self._extra if isinstance(self._extra, dict) else {}

# 4. load() 中 extra 加载：
if ep.exists():
    e: object = json.loads(ep.read_text())
    self._extra = e if isinstance(e, dict) else {}
    # 原有 dict 类型检查保留
```

- [ ] **步骤 3：运行测试验证**

运行：`uv run pytest tests/stores/test_faiss_index.py -v`
预期：PASS

- [ ] **步骤 4：Commit**

```bash
git add app/memory/memory_bank/faiss_index.py tests/stores/test_faiss_index.py
git commit -m "fix: faiss_index _next_id sync, dim mismatch raise, json null defense"
```

---

### 任务 4：最终集成验证

- [ ] **步骤 1：运行完整检查流程**

```bash
uv run ruff check --fix
uv run ruff format
uv run ty check
```

- [ ] **步骤 2：运行全部测试**

```bash
uv run pytest
```

- [ ] **步骤 3：如有失败修复后重复 1-2**

- [ ] **步骤 4：Commit 收尾**

```bash
git add -A
git commit -m "fix: resolve integration issues after memory system improvements"
```
