# MemoryBank 深度重构实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将 DrivePal 记忆系统从单用户 Facade 架构重构为多用户直接 store 架构，同时修复正确性问题并补全缺失功能。

**架构：** 删除 `MemoryModule`/`MemoryMode`/工厂注册表 Facade 层，将 `FaissIndex` 改为多用户 `FaissIndexManager`（per-user 索引隔离），所有 store 方法加 `user_id` 参数，批量嵌入、遗忘路径统一、metadata 可变引用管控、参考日期自动计算。

**技术栈：** Python 3.14 + FAISS + Pydantic + asyncio

---

## 文件结构

### 创建/重写

| 文件 | 职责 |
|------|------|
| `app/memory/memory_bank/faiss_index.py` | 多用户 `FaissIndexManager` + `_UserIndex` 数据类（重写） |
| `app/memory/memory_bank/store.py` | 多用户 `MemoryBankStore` |
| `app/memory/memory_bank/retrieval.py` | 多用户 `RetrievalPipeline` |
| `app/memory/memory_bank/summarizer.py` | 多用户 `Summarizer` |
| `app/memory/memory_bank/forget.py` | 精简：仅保留纯函数和枚举 |
| `app/memory/interfaces.py` | 多用户 `MemoryStore` Protocol |
| `app/memory/__init__.py` | 导出 `MemoryBankStore` + schemas |
| `app/memory/singleton.py` | 简化为 `MemoryBankStore` 单例 |
| `app/agents/workflow.py` | 改用 `MemoryBankStore`，去掉 `MemoryMode` |
| `app/api/resolvers/mutation.py` | 改用 `MemoryBankStore`，去掉 `MemoryMode` |
| `app/api/resolvers/query.py` | 改用 `MemoryBankStore`，去掉 `MemoryMode` |
| `app/api/graphql_schema.py` | `MemoryModeEnum` 改为 `UserInput`（user_id 字段） |

### 删除

| 文件 | 原因 |
|------|------|
| `app/memory/memory.py` | Facade 层 |
| `app/memory/types.py` | `MemoryMode` 仅 1 值 |
| `app/memory/stores/__init__.py` | 无外部引用 |
| `tests/test_memory_module_facade.py` | Facade 测试 |
| `tests/test_memory_store_contract.py` | 基于 Facade 的 contract 测试 |

### 删除（无重命名）

所有删除在任务 6 统一执行。

### 不变

| 文件 | 说明 |
|------|------|
| `app/memory/schemas.py` | 数据模型不变 |
| `app/memory/embedding_client.py` | 不变 |
| `app/memory/utils.py` | 不变 |
| `app/memory/memory_bank/llm.py` | 不变 |

### 测试文件

| 文件 | 操作 |
|------|------|
| `tests/stores/test_faiss_index.py` | 删除，由 `test_faiss_index_manager.py` 替代 |
| `tests/stores/test_faiss_index_manager.py` | 新建 |
| `tests/stores/test_retrieval.py` | 重写适配多用户 |
| `tests/stores/test_summarizer.py` | 重写适配多用户 |
| `tests/stores/test_memory_bank_store.py` | 重写适配多用户 |
| `tests/stores/test_forget.py` | 删除 `ForgettingCurve` 测试，保留纯函数测试 |
| `tests/test_memory_bank.py` | 重写适配多用户 |
| `tests/test_graphql.py` | 适配新 `user_id` 参数 |
| `tests/test_embedding.py` | 重写适配新接口 |
| `tests/test_storage.py` | 重写适配新接口 |
| `tests/test_embedding_client.py` | 不变 |
| `tests/test_cosine_similarity.py` | 不变 |
| `tests/test_schemas.py` | 不变 |
| `tests/test_memory_module_facade.py` | 删除 |
| `tests/test_memory_store_contract.py` | 删除 |

---

## 任务 1：FaissIndexManager

**文件：**
- 创建：`app/memory/memory_bank/faiss_index.py`（重写）
- 测试：`tests/stores/test_faiss_index_manager.py`

- [ ] **步骤 1：编写失败的测试**

测试要点：
- `_UserIndex` 数据类字段正确
- `FaissIndexManager(data_dir)` 构造
- `load(user_id)` 延迟加载，不存在的 user_id 创建空索引
- `add_vector(user_id, text, emb, ts)` 返回 faiss_id，递增
- `get_metadata(user_id)` 返回 deep copy，修改副本不影响内部
- `update_metadata(user_id, faiss_id, updates)` 显式更新
- `batch_update_metadata(user_id, {meta_idx: updates})` 批量更新
- `search(user_id, query_emb, top_k)` 检索结果含 `_meta_idx`
- `remove_vectors(user_id, faiss_ids)` 删除后 total 减少，next_id 正确
- `save(user_id)` + `load(user_id)` 持久化往返
- `get_extra(user_id)` / extra 持久化
- 多 user_id 隔离：user_a 的 add 不影响 user_b 的 metadata
- 损坏的 metadata.json 导致空索引重建而非崩溃
- `parse_speaker_line` 静态方法保留

```python
# tests/stores/test_faiss_index_manager.py 核心测试结构
import pytest
import numpy as np
from pathlib import Path

from app.memory.memory_bank.faiss_index import FaissIndexManager


@pytest.fixture
def manager(tmp_path: Path) -> FaissIndexManager:
    return FaissIndexManager(tmp_path)


async def test_add_and_search(manager: FaissIndexManager) -> None:
    uid = "user_1"
    emb = [0.1] * 1536
    fid = await manager.add_vector(uid, "hello world", emb, "2026-01-01T00:00:00")
    assert fid == 0
    assert await manager.total(uid) == 1

    results = await manager.search(uid, emb, top_k=5)
    assert len(results) == 1
    assert results[0]["text"] == "hello world"
    assert results[0]["_meta_idx"] == 0


async def test_metadata_deep_copy(manager: FaissIndexManager) -> None:
    uid = "user_1"
    emb = [0.1] * 1536
    await manager.add_vector(uid, "test", emb, "2026-01-01T00:00:00")
    meta = manager.get_metadata(uid)
    meta[0]["text"] = "MUTATED"
    assert manager.get_metadata(uid)[0]["text"] == "test"


async def test_multi_user_isolation(manager: FaissIndexManager) -> None:
    emb = [0.1] * 1536
    await manager.add_vector("user_a", "text_a", emb, "2026-01-01T00:00:00")
    await manager.add_vector("user_b", "text_b", emb, "2026-01-01T00:00:00")
    assert await manager.total("user_a") == 1
    assert await manager.total("user_b") == 1
    assert manager.get_metadata("user_a")[0]["text"] == "text_a"


async def test_persistence_roundtrip(manager: FaissIndexManager, tmp_path: Path) -> None:
    uid = "user_1"
    emb = [0.1] * 1536
    await manager.add_vector(uid, "persist me", emb, "2026-01-01T00:00:00")
    await manager.save(uid)

    manager2 = FaissIndexManager(tmp_path)
    await manager2.load(uid)
    assert await manager2.total(uid) == 1
    assert manager2.get_metadata(uid)[0]["text"] == "persist me"


async def test_corrupted_metadata_rebuilds(tmp_path: Path) -> None:
    uid = "user_1"
    user_dir = tmp_path / f"user_{uid}"
    user_dir.mkdir(parents=True)
    (user_dir / "metadata.json").write_text("NOT JSON")
    (user_dir / "index.faiss").write_bytes(b"")

    manager = FaissIndexManager(tmp_path)
    await manager.load(uid)
    assert await manager.total(uid) == 0
```

- [ ] **步骤 2：运行测试验证失败**

```bash
nortk uv run pytest tests/stores/test_faiss_index_manager.py -v
```

预期：FAIL，`ModuleNotFoundError: No module named 'app.memory.faiss_index'`

- [ ] **步骤 3：编写 FaissIndexManager 实现**

接口 + 思路：

```python
# app/memory/memory_bank/faiss_index.py
from __future__ import annotations

import copy
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
    """单用户的 FAISS 索引 + 元数据。"""
    index: faiss.IndexIDMap
    metadata: list[dict[str, Any]] = field(default_factory=list)
    next_id: int = 0
    id_to_meta: dict[int, int] = field(default_factory=dict)
    speakers: set[str] = field(default_factory=set)
    extra: dict[str, Any] = field(default_factory=dict)


def _validate_metadata_structure(meta: object) -> list[dict[str, Any]]:
    """校验 metadata 为 list[dict]，每个 dict 含 faiss_id（int，无重复）。"""
    if not isinstance(meta, list):
        msg = "metadata root is not list"
        raise TypeError(msg)
    seen: set[int] = set()
    for i, m in enumerate(meta):
        if not isinstance(m, dict) or "faiss_id" not in m:
            msg = f"entry {i}: invalid"
            raise ValueError(msg)
        entry: dict[str, Any] = m
        fid: object = entry["faiss_id"]
        if not isinstance(fid, int):
            msg = f"entry {i}: faiss_id={fid!r} 不是整数"
            raise TypeError(msg)
        if fid in seen:
            msg = f"entry {i}: 重复 faiss_id={fid}"
            raise ValueError(msg)
        seen.add(fid)
    return meta


def _validate_index_count(idx: faiss.Index, meta_len: int) -> None:
    """校验索引条目数与 metadata 数一致。"""
    if idx.ntotal != meta_len:
        msg = f"count mismatch {idx.ntotal} vs {meta_len}"
        raise ValueError(msg)


class FaissIndexManager:
    """多用户 FAISS 索引管理器。"""

    def __init__(self, data_dir: Path, embedding_dim: int = DEFAULT_EMBEDDING_DIM) -> None:
        self._data_dir = data_dir
        self._dim = embedding_dim
        self._users: dict[str, _UserIndex] = {}

    # ── 用户目录 ──
    def _user_dir(self, user_id: str) -> Path:
        return self._data_dir / f"user_{user_id}"

    # ── 加载/保存 ──
    async def load(self, user_id: str) -> None:
        """延迟加载；已加载则跳过。"""
        if user_id in self._users:
            return
        user_dir = self._user_dir(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        ip = user_dir / "index.faiss"
        mp = user_dir / "metadata.json"
        ep = user_dir / "extra_metadata.json"

        if ip.exists() and mp.exists():
            # 尝试加载；损坏则回退空索引
            try:
                idx = faiss.read_index(str(ip))
                raw_meta = json.loads(mp.read_text())
                meta = _validate_metadata_structure(raw_meta)
                _validate_index_count(idx, len(meta))
            except (json.JSONDecodeError, OSError, TypeError, ValueError, RuntimeError) as exc:
                logger.warning("FaissIndexManager: 损坏 user=%s，重建空索引: %s", user_id, exc)
                for f in (ip, mp, ep):
                    f.unlink(missing_ok=True)
                self._users[user_id] = _UserIndex(index=faiss.IndexIDMap(faiss.IndexFlatIP(self._dim)))
                return
            ui = _UserIndex(
                index=idx,
                metadata=meta,
                next_id=max(m["faiss_id"] for m in meta) + 1 if meta else 0,
                id_to_meta={m["faiss_id"]: i for i, m in enumerate(meta)},
            )
            self._rebuild_speakers(ui)
            if ep.exists():
                try:
                    e = json.loads(ep.read_text())
                    ui.extra = e if isinstance(e, dict) else {}
                except (json.JSONDecodeError, OSError, TypeError, ValueError):
                    ep.unlink(missing_ok=True)
            self._users[user_id] = ui
        else:
            self._users[user_id] = _UserIndex(index=faiss.IndexIDMap(faiss.IndexFlatIP(self._dim)))

    async def save(self, user_id: str) -> None:
        ui = self._users.get(user_id)
        if ui is None or ui.index.ntotal == 0 and not ui.metadata:
            return
        user_dir = self._user_dir(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        faiss.write_index(ui.index, str(user_dir / "index.faiss"))
        (user_dir / "metadata.json").write_text(
            json.dumps(ui.metadata, ensure_ascii=False, indent=2)
        )
        if ui.extra:
            (user_dir / "extra_metadata.json").write_text(
                json.dumps(ui.extra, ensure_ascii=False, indent=2)
            )

    # ── 向量操作 ──
    async def add_vector(
        self, user_id: str, text: str, embedding: list[float],
        timestamp: str, extra_meta: dict | None = None,
    ) -> int:
        if user_id not in self._users:
            await self.load(user_id)
        ui = self._users[user_id]
        emb_dim = len(embedding)
        if ui.index.d != emb_dim:
            # 首次添加时可能需要调整维度
            if ui.index.ntotal == 0:
                ui.index = faiss.IndexIDMap(faiss.IndexFlatIP(emb_dim))
            else:
                raise ValueError(f"维度不匹配: index={ui.index.d}, vector={emb_dim}")
        fid = ui.next_id
        ui.next_id += 1
        vec = np.array([embedding], dtype=np.float32)
        faiss.normalize_L2(vec)
        ui.index.add_with_ids(vec, np.array([fid], dtype=np.int64))
        entry: dict[str, Any] = {
            "faiss_id": fid,
            "text": text,
            "timestamp": timestamp,
            "memory_strength": 1,
            "last_recall_date": timestamp[:_TIMESTAMP_LENGTH] if len(timestamp) >= _TIMESTAMP_LENGTH else timestamp,
        }
        if extra_meta:
            entry.update(extra_meta)
            for spk in extra_meta.get("speakers", []):
                ui.speakers.add(spk)
        ui.metadata.append(entry)
        ui.id_to_meta[fid] = len(ui.metadata) - 1
        return fid

    async def search(self, user_id: str, query_emb: list[float], top_k: int) -> list[dict]:
        ui = self._users.get(user_id)
        if ui is None or ui.index.ntotal == 0:
            return []
        k = min(top_k, ui.index.ntotal)
        vec = np.array([query_emb], dtype=np.float32)
        faiss.normalize_L2(vec)
        scores, indices = ui.index.search(vec, k)
        results = []
        for s, fid in zip(scores[0], indices[0], strict=True):
            mi = ui.id_to_meta.get(int(fid))
            if mi is None:
                continue
            m = dict(ui.metadata[mi])
            m["score"] = float(s)
            m["_meta_idx"] = mi
            results.append(m)
        return results

    async def remove_vectors(self, user_id: str, faiss_ids: list[int]) -> None:
        ui = self._users.get(user_id)
        if ui is None:
            return
        ui.index.remove_ids(np.array(faiss_ids, dtype=np.int64))
        id_set = set(faiss_ids)
        ui.metadata = [m for m in ui.metadata if m["faiss_id"] not in id_set]
        ui.id_to_meta = {m["faiss_id"]: i for i, m in enumerate(ui.metadata)}
        ui.next_id = max((m["faiss_id"] for m in ui.metadata), default=-1) + 1
        self._rebuild_speakers(ui)

    # ── metadata 访问（不可变保护）──
    def get_metadata(self, user_id: str) -> list[dict]:
        ui = self._users.get(user_id)
        if ui is None:
            return []
        return copy.deepcopy(ui.metadata)

    async def update_metadata(self, user_id: str, faiss_id: int, updates: dict) -> None:
        ui = self._users.get(user_id)
        if ui is None:
            return
        mi = ui.id_to_meta.get(faiss_id)
        if mi is not None:
            ui.metadata[mi].update(updates)

    async def batch_update_metadata(self, user_id: str, updates: dict[int, dict]) -> None:
        """批量更新 {meta_idx: {field: value}}。"""
        ui = self._users.get(user_id)
        if ui is None:
            return
        for meta_idx, fields in updates.items():
            if 0 <= meta_idx < len(ui.metadata):
                ui.metadata[meta_idx].update(fields)

    def get_metadata_by_id(self, user_id: str, faiss_id: int) -> dict | None:
        ui = self._users.get(user_id)
        if ui is None:
            return None
        mi = ui.id_to_meta.get(faiss_id)
        return dict(ui.metadata[mi]) if mi is not None else None

    # ── extra metadata ──
    def get_extra(self, user_id: str) -> dict:
        ui = self._users.get(user_id)
        if ui is None:
            return {}
        return ui.extra

    # ── 统计 ──
    async def total(self, user_id: str) -> int:
        ui = self._users.get(user_id)
        return ui.index.ntotal if ui is not None else 0

    def is_loaded(self, user_id: str) -> bool:
        return user_id in self._users

    def get_all_speakers(self, user_id: str) -> list[str]:
        ui = self._users.get(user_id)
        return sorted(ui.speakers) if ui is not None else []

    # ── 静态方法 ──
    @staticmethod
    def parse_speaker_line(line: str) -> tuple[str | None, str]:
        colon_pos = line.find(": ")
        if colon_pos > 0:
            return line[:colon_pos].strip(), line[colon_pos + 2:].strip()
        return None, line.strip()

    # ── 内部 ──
    @staticmethod
    def _rebuild_speakers(ui: _UserIndex) -> None:
        ui.speakers.clear()
        for m in ui.metadata:
            for spk in m.get("speakers", []):
                ui.speakers.add(spk)
```

- [ ] **步骤 4：运行测试验证通过**

```bash
nortk uv run pytest tests/stores/test_faiss_index_manager.py -v
```

预期：全部 PASS

- [ ] **步骤 5：删除旧 faiss_index.py，Commit**

```bash
git add -A && git commit -m "refactor: rewrite FaissIndex as multi-user FaissIndexManager"
```

---

## 任务 2：forget.py 精简

**文件：**
- 修改：`app/memory/memory_bank/forget.py`
- 修改：`tests/stores/test_forget.py`

- [ ] **步骤 1：编写失败的测试**

删除 `ForgettingCurve` 相关测试。保留 `forgetting_retention`、`compute_ingestion_forget_ids`、`ForgetMode` 的测试。

- [ ] **步骤 2：运行测试验证失败**

```bash
nortk uv run pytest tests/stores/test_forget.py -v
```

预期：PASS（测试未移除 ForgettingCurve 前暂时通过）

- [ ] **步骤 3：修改 forget.py**

删除 `ForgettingCurve` 类、`FORGET_INTERVAL_SECONDS`、`_resolve_forget_mode`。保留：
- `forgetting_retention(days, strength)` 全局函数
- `ForgetMode` 枚举
- `SOFT_FORGET_THRESHOLD` 常量
- `FORGETTING_TIME_SCALE` 常量
- `compute_ingestion_forget_ids` 纯函数

- [ ] **步骤 4：修改测试，删除 ForgettingCurve 相关测试**

- [ ] **步骤 5：运行测试验证通过**

```bash
nortk uv run pytest tests/stores/test_forget.py -v
```

- [ ] **步骤 6：Commit**

```bash
git add -A && git commit -m "refactor: simplify forget.py, remove ForgettingCurve class"
```

---

## 任务 3：RetrievalPipeline 多用户化

**文件：**
- 修改：`app/memory/memory_bank/retrieval.py`
- 修改：`tests/stores/test_retrieval.py`

- [ ] **步骤 1：编写失败的测试**

测试要点：
- `RetrievalPipeline(index_manager, embedding_client)` 构造
- `search(user_id, query, top_k, reference_date)` 返回 `list[dict]`
- `_compute_strength_updates` 纯函数返回 `{meta_idx: {"memory_strength": ..., "last_recall_date": ...}}`
- 邻居合并、重叠去重、说话人降权算法不变

- [ ] **步骤 2：运行测试验证失败**

- [ ] **步骤 3：重写 retrieval.py**

核心变更：
1. 构造函数接收 `FaissIndexManager`（从 `app.memory.memory_bank.faiss_index` 导入）
2. `search` 方法签名：`async def search(self, user_id, query, top_k=5, reference_date=None) -> tuple[list[dict], dict[int, dict]]`
3. 内部通过 `self._index_manager.get_metadata(user_id)` 拿副本
4. 通过 `self._index_manager.search(user_id, query_emb, coarse_k)` 执行 FAISS 检索
5. `_update_memory_strengths` → `_compute_strength_updates`：纯函数，返回更新字典
6. 返回 `(merged_results, strength_updates)`
7. 模块级函数（`_gather_neighbor_indices`、`_trim_to_chunk_size`、`_build_neighbor_result`、`_merge_overlapping_results` 等）**不变**

- [ ] **步骤 4：运行测试验证通过**

```bash
nortk uv run pytest tests/stores/test_retrieval.py -v
```

- [ ] **步骤 5：Commit**

```bash
git add -A && git commit -m "refactor: multi-user RetrievalPipeline with pure strength updates"
```

---

## 任务 4：Summarizer 多用户化

**文件：**
- 修改：`app/memory/memory_bank/summarizer.py`
- 修改：`tests/stores/test_summarizer.py`

- [ ] **步骤 1：编写失败的测试**

测试要点：
- `Summarizer(llm, index_manager)` 构造
- `get_daily_summary(user_id, date_key)` — 已存在日期跳过
- `get_overall_summary(user_id)` — 已存在跳过，空结果存 GENERATION_EMPTY
- `get_daily_personality(user_id, date_key)` — 已存在跳过
- `get_overall_personality(user_id)` — 已存在跳过

- [ ] **步骤 2：运行测试验证失败**

- [ ] **步骤 3：重写 summarizer.py**

核心变更：
1. 构造函数接收 `LlmClient` + `FaissIndexManager`
2. 所有方法加 `user_id: str` 第一参数
3. 内部通过 `self._index_manager.get_metadata(user_id)` 获取副本
4. extra 通过 `self._index_manager.get_extra(user_id)` 获取可变引用
5. 不可变保护逻辑不变
6. prompt 内容不变

- [ ] **步骤 4：运行测试验证通过**

```bash
nortk uv run pytest tests/stores/test_summarizer.py -v
```

- [ ] **步骤 5：Commit**

```bash
git add -A && git commit -m "refactor: multi-user Summarizer"
```

---

## 任务 5：MemoryBankStore 多用户化

**文件：**
- 修改：`app/memory/memory_bank/store.py`
- 修改：`tests/stores/test_memory_bank_store.py`
- 修改：`tests/test_memory_bank.py`

- [ ] **步骤 1：编写失败的测试**

测试要点：
- `MemoryBankStore(data_dir, embedding_model, chat_model)` — embedding/chat 必需
- `write(user_id, event)` — 批量嵌入，配对逻辑
- `write_interaction(user_id, query, response, event_type, *, user_name, ai_name)` — 显式参数
- `search(user_id, query, top_k)` — 返回 `list[SearchResult]`，含 overall context
- `get_history(user_id, limit)` — 返回 `list[MemoryEvent]`
- `get_event_type(user_id, event_id)` — 返回 `str | None`
- `update_feedback(user_id, event_id, feedback)` — 静默忽略
- `_get_reference_date(user_id)` — 从 metadata 自动计算
- 多用户隔离：user_a 的 write 不影响 user_b 的 search
- 遗忘开关：`MEMORYBANK_ENABLE_FORGETTING=1` 时 `_forget_at_ingestion` 生效
- 后台摘要：write 后触发异步摘要

- [ ] **步骤 2：运行测试验证失败**

- [ ] **步骤 3：重写 store.py**

接口 + 思路（完整代码量较大，按接口 + 关键逻辑描述）：

构造函数：
```python
def __init__(
    self,
    data_dir: Path,
    embedding_model: EmbeddingModel,
    chat_model: ChatModel,
    seed: int | None = None,
    reference_date: str | None = None,
) -> None:
    self._index_manager = FaissIndexManager(data_dir)
    self._embedding_client = EmbeddingClient(embedding_model)
    self._rng = random.Random(seed)
    self._seed_provided = seed is not None
    self._reference_date = reference_date
    self._llm = LlmClient(chat_model, rng=self._rng)
    self._retrieval = RetrievalPipeline(self._index_manager, self._embedding_client)
    self._summarizer = Summarizer(self._llm, self._index_manager)
    self._forgetting_enabled = os.getenv("MEMORYBANK_ENABLE_FORGETTING", "0").lower() in ("1", "true", "yes")
```

`write(user_id, event)`：
- 解析行 → 配对 → 收集所有 pair_texts
- `await self._embedding_client.encode_batch(pair_texts)` 批量嵌入
- 逐条 `add_vector`
- 遗忘 + save + 后台摘要

`write_interaction(user_id, query, response, event_type, *, user_name, ai_name)`：
- 单条 encode
- add_vector
- 遗忘 + save + 后台摘要

`search(user_id, query, top_k)`：
- `results, strength_updates = await self._retrieval.search(user_id, query, top_k, ref_date)`
- `await self._index_manager.batch_update_metadata(user_id, strength_updates)`
- 从 extra 取 overall_summary / overall_personality 构造前置 SearchResult
- 有更新时 save

`_get_reference_date(user_id)`：
- 优先构造器 `reference_date`
- 未设置时从 metadata 最新 timestamp + 1 天

`_forget_at_ingestion(user_id)`：
- 调用 `compute_ingestion_forget_ids(metadata, ref_date, rng, mode)`
- 调用 `remove_vectors(user_id, ids)`

`_background_summarize(user_id, date_key)`：
- 日摘要 → add_vector → save
- overall_summary + daily_personality + overall_personality → save

`get_history(user_id, limit)`：
- `await self._index_manager.load(user_id)`
- `metadata = self._index_manager.get_metadata(user_id)`
- 过滤 `type == "daily_summary"` 的条目（与当前实现一致）
- 取最后 `limit` 条，构造 `MemoryEvent(content=raw_content or text, type=event_type, memory_strength=...)`

`get_event_type(user_id, event_id)`：
- `await self._index_manager.load(user_id)`
- `m = self._index_manager.get_metadata_by_id(user_id, int(event_id))`
- 返回 `m.get("event_type") or "reminder"`，解析失败返回 `None`

`update_feedback(user_id, event_id, feedback)`：
- 静默忽略（`pass`），与当前实现一致。反馈功能已移除但接口保留。

类属性：`store_name = "memory_bank"`, `requires_embedding = True`, `requires_chat = True`

- [ ] **步骤 4：运行测试验证通过**

```bash
nortk uv run pytest tests/stores/test_memory_bank_store.py tests/test_memory_bank.py -v
```

- [ ] **步骤 5：Commit**

```bash
git add -A && git commit -m "refactor: multi-user MemoryBankStore with batch embedding"
```

---

## 任务 6：接口层 + API 层 + Workflow 统一适配

> **注意：** 此任务必须原子执行——删除旧文件、重写接口、适配 API/Workflow 同时完成，
> 否则中间状态会因导入缺失而无法通过 lint/type check。

**文件：**
- 修改：`app/memory/interfaces.py`
- 修改：`app/memory/__init__.py`
- 修改：`app/memory/singleton.py`
- 修改：`app/memory/memory_bank/__init__.py`
- 修改：`app/api/graphql_schema.py`
- 修改：`app/api/resolvers/mutation.py`
- 修改：`app/api/resolvers/query.py`
- 修改：`app/agents/workflow.py`
- 删除：`app/memory/memory.py`
- 删除：`app/memory/types.py`
- 删除：`app/memory/stores/__init__.py`（整个 stores/ 目录）

- [ ] **步骤 1：重写 interfaces.py**

```python
# app/memory/interfaces.py
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.memory.schemas import FeedbackData, InteractionResult, MemoryEvent, SearchResult


class MemoryStore(Protocol):
    """记忆存储接口，多用户版。"""
    store_name: str
    requires_embedding: bool
    requires_chat: bool

    async def write(self, user_id: str, event: MemoryEvent) -> str: ...
    async def write_interaction(
        self, user_id: str, query: str, response: str,
        event_type: str = "reminder", *, user_name: str = "User", ai_name: str = "AI",
    ) -> InteractionResult: ...
    async def search(self, user_id: str, query: str, top_k: int = 5) -> list[SearchResult]: ...
    async def get_history(self, user_id: str, limit: int = 10) -> list[MemoryEvent]: ...
    async def get_event_type(self, user_id: str, event_id: str) -> str | None: ...
    async def update_feedback(self, user_id: str, event_id: str, feedback: FeedbackData) -> None: ...
```

- [ ] **步骤 2：重写 __init__.py**

```python
# app/memory/__init__.py
from app.memory.memory_bank import MemoryBankStore
from app.memory.schemas import InteractionRecord, InteractionResult, MemoryEvent, SearchResult

__all__ = [
    "InteractionRecord",
    "InteractionResult",
    "MemoryEvent",
    "MemoryBankStore",
    "SearchResult",
]
```

- [ ] **步骤 3：重写 singleton.py**

```python
# app/memory/singleton.py
import threading
from app.config import DATA_DIR
from app.memory.memory_bank import MemoryBankStore
from app.models.chat import get_chat_model
from app.models.embedding import get_cached_embedding_model

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

- [ ] **步骤 4：更新 memory_bank/__init__.py**

```python
# app/memory/memory_bank/__init__.py
from app.memory.memory_bank.store import MemoryBankStore

__all__ = ["MemoryBankStore"]
```

- [ ] **步骤 5：删除旧文件**

```bash
rm app/memory/memory.py
rm app/memory/types.py
rm -rf app/memory/stores/
```

- [ ] **步骤 6：修改 graphql_schema.py**

将 `MemoryModeEnum` 替换为 user_id 输入：

```python
# 删除 MemoryModeEnum
# 在 ProcessQueryInput 中：
class ProcessQueryInput:
    query: str
    user_id: str = "default"
    context: DrivingContextInput | None = None

# 在 FeedbackInput 中：
class FeedbackInput:
    event_id: str
    action: str
    user_id: str = "default"
    modified_content: str | None = None
```

- [ ] **步骤 7：修改 mutation.py**

```python
# 删除 from app.memory.types import MemoryMode
from app.memory.singleton import get_memory_store

# process_query:
mm = get_memory_store()
workflow = AgentWorkflow(data_dir=DATA_DIR, memory_store=mm, user_id=query_input.user_id)

# submit_feedback:
mm = get_memory_store()
actual_type = await mm.get_event_type(feedback_input.user_id, feedback_input.event_id)
await mm.update_feedback(feedback_input.user_id, feedback_input.event_id, feedback)
```

- [ ] **步骤 8：修改 query.py**

```python
# 删除 from app.memory.types import MemoryMode
from app.memory.singleton import get_memory_store

# history: 参数改为 user_id: str = "default"
mm = get_memory_store()
events = await mm.get_history(user_id=user_id, limit=limit)
```

- [ ] **步骤 9：修改 workflow.py**

核心变更：
- 删除 `from app.memory.memory import MemoryModule` 和 `from app.memory.types import MemoryMode`
- 导入 `from app.memory.memory_bank import MemoryBankStore`
- 构造函数参数：`memory_store: MemoryBankStore` + `user_id: str = "default"`
- 所有 `self.memory_module.search(..., mode=...)` → `self._memory_store.search(user_id=self._user_id, query=...)`
- 所有 `self.memory_module.write_interaction(..., mode=...)` → `self._memory_store.write_interaction(user_id=self._user_id, ...)`
- 所有 `self.memory_module.get_history(..., mode=...)` → `self._memory_store.get_history(user_id=self._user_id, ...)`
- `self.memory_module.chat_model` → 构造时单独传入 `chat_model` 参数并保存为 `self._chat_model`

- [ ] **步骤 10：运行 lint + type check**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```

- [ ] **步骤 11：Commit**

```bash
git add -A && git commit -m "refactor: remove facade, adapt API/Workflow to multi-user store"
```

---

## 任务 7：测试清理和重写
- 删除：`tests/test_memory_module_facade.py`
- 删除：`tests/test_memory_store_contract.py`
- 重写：`tests/test_memory_bank.py`
- 重写：`tests/test_embedding.py`
- 重写：`tests/test_storage.py`
- 修改：`tests/test_graphql.py`

- [ ] **步骤 1：删除 Facade 测试**

```bash
rm tests/test_memory_module_facade.py
rm tests/test_memory_store_contract.py
```

- [ ] **步骤 2：重写 test_memory_bank.py**

端到端集成测试：write → search → get_history，多用户隔离。

- [ ] **步骤 3：重写 test_embedding.py 和 test_storage.py**

改为直接使用 `MemoryBankStore`。

- [ ] **步骤 4：修改 test_graphql.py**

适配新 `user_id` 参数（替代 `memory_mode`）。

- [ ] **步骤 5：运行全量测试**

```bash
nortk uv run pytest
```

- [ ] **步骤 6：Commit**

```bash
git add -A && git commit -m "test: rewrite tests for multi-user MemoryBankStore"
```

---

## 任务 8：最终验证

- [ ] **步骤 1：运行 lint + type check**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```

- [ ] **步骤 2：运行全量测试**

```bash
nortk uv run pytest
```

- [ ] **步骤 3：手动验证多用户隔离**

```bash
nortk uv run python -c "
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from app.memory.memory_bank import MemoryBankStore

async def main():
    # duck-typing mock: 满足 EmbeddingModel/ChatModel 所需的 encode/generate 接口
    emb = MagicMock()
    emb.encode = AsyncMock(return_value=[0.1]*1536)
    emb.batch_encode = AsyncMock(return_value=[[0.1]*1536])
    chat = MagicMock()
    chat.generate = AsyncMock(return_value='summary text')
    store = MemoryBankStore(Path('/tmp/test_memory_mb'), emb, chat)
    r1 = await store.write_interaction('alice', 'hello', 'hi')
    r2 = await store.write_interaction('bob', 'bonjour', 'salut')
    s1 = await store.search('alice', 'hello')
    s2 = await store.search('bob', 'bonjour')
    print(f'alice results: {len(s1)}, bob results: {len(s2)}')
    assert len(s1) >= 1
    assert len(s2) >= 1
    print('OK')

asyncio.run(main())
"
```

- [ ] **步骤 4：Commit**

```bash
git add -A && git commit -m "refactor: memory bank deep refactoring complete"
```
