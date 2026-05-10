# 代码优化实现计划

> **面向 AI 代理的工作者：** 使用 superpowers:subagent-driven-development 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法跟踪进度。

**目标：** 修复 10 项代码层问题——3 项性能优化、3 项检索增强、2 项架构小修、2 项清理。

**架构：** 按文件依赖排序，先加 config 字段和依赖，再改核心模块（retrieval/rules/chat/embedding），最后改上层调用方。每任务含测试步骤。

**技术栈：** Python 3.14, pytest (asyncio_mode=auto), faiss-cpu, rank-bm25, openai, ruff, ty

---

## 任务 1：添加 rank-bm25 依赖

**文件：**
- 修改：`pyproject.toml`

- [ ] **步骤 1：添加依赖**

```toml
# 在 dependencies 列表末尾（faiss-cpu 之后）添加：
    "rank-bm25>=0.2.2",
```

- [ ] **步骤 2：安装依赖并验证**

```bash
uv sync
python -c "from rank_bm25 import BM25Okapi; print('ok')"
```
预期：输出 `ok`

- [ ] **步骤 3：Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add rank-bm25 for BM25 search fallback"
```

---

## 任务 2：MemoryBankConfig 新增字段（Fixes 4, 5, 6, 7）

**文件：**
- 修改：`app/memory/memory_bank/config.py`

**接口与思路：**
在 `MemoryBankConfig` 类中新增 8 个字段，均带环境变量映射和校验：

```
# Fix 4: 记忆强度上限
max_memory_strength: int = 10          # MEMORYBANK_MAX_MEMORY_STRENGTH

# Fix 5: 检索加权公式 alpha
retrieval_alpha: float = 0.7           # MEMORYBANK_RETRIEVAL_ALPHA

# Fix 6: BM25 回退
bm25_fallback_enabled: bool = True     # MEMORYBANK_BM25_FALLBACK_ENABLED
bm25_fallback_threshold: float = 0.5   # MEMORYBANK_BM25_FALLBACK_THRESHOLD

# Fix 7: FAISS 索引类型
index_type: Literal["flat", "ivf_flat"] = "flat"  # MEMORYBANK_INDEX_TYPE
ivf_nlist: int = 128                   # MEMORYBANK_IVF_NLIST
```

校验规则：
- `max_memory_strength >= 1`，否则回退 10
- `0.0 < retrieval_alpha <= 1.0`，否则回退 0.7
- `0.0 < bm25_fallback_threshold <= 1.0`，否则回退 0.5
- `ivf_nlist >= 1`，否则回退 128

- [ ] **步骤 1：编写测试**

```python
# tests/test_memory_bank.py 中新增

import os

def test_max_memory_strength_default():
    config = MemoryBankConfig()
    assert config.max_memory_strength == 10

def test_max_memory_strength_env(monkeypatch):
    monkeypatch.setenv("MEMORYBANK_MAX_MEMORY_STRENGTH", "5")
    config = MemoryBankConfig()
    assert config.max_memory_strength == 5

def test_max_memory_strength_negative_guarded():
    config = MemoryBankConfig(max_memory_strength=0)
    assert config.max_memory_strength == 10

def test_retrieval_alpha_default():
    config = MemoryBankConfig()
    assert config.retrieval_alpha == 0.7

def test_retrieval_alpha_out_of_range_guarded():
    config = MemoryBankConfig(retrieval_alpha=1.5)
    assert config.retrieval_alpha == 0.7

def test_bm25_fallback_defaults():
    config = MemoryBankConfig()
    assert config.bm25_fallback_enabled is True
    assert config.bm25_fallback_threshold == 0.5

def test_index_type_default():
    config = MemoryBankConfig()
    assert config.index_type == "flat"

def test_ivf_nlist_default():
    config = MemoryBankConfig()
    assert config.ivf_nlist == 128
```

- [ ] **步骤 2：运行测试验证失败**

```bash
uv run pytest tests/test_memory_bank.py -k "test_max_memory_strength or test_retrieval_alpha or test_bm25_fallback or test_index_type or test_ivf_nlist" -v
```
预期：FAIL（AttributeError: 'MemoryBankConfig' object has no attribute）

- [ ] **步骤 3：实现 config 字段**

在 `MemoryBankConfig`（`config.py` 中约第 35 行，`embedding_min_similarity` 之后）添加上述字段和校验器。参考现有校验器模式（用 `@field_validator`）。

- [ ] **步骤 4：运行测试验证通过**

```bash
uv run pytest tests/test_memory_bank.py -k "test_max_memory_strength or test_retrieval_alpha or test_bm25_fallback or test_index_type or test_ivf_nlist" -v
```
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add app/memory/memory_bank/config.py tests/test_memory_bank.py
git commit -m "feat(memory): add config fields for strength cap, retrieval alpha, BM25 fallback, index type"
```

---

## 任务 3：ChatModel 客户端复用（Fix 2）

**文件：**
- 修改：`app/models/chat.py`
- 测试：`tests/test_chat.py`（如不存在则新建）

**接口与思路：**
模块级字典缓存 `AsyncOpenAI` 实例，键为 `(base_url, api_key_hash)`。在 `generate()` 和 `generate_stream()` 中替换 `async with self._create_client(provider) as client` 为 `client = await _get_cached_client(provider)`。新增 `close_client_cache()` 用于 lifespan 关闭。

关键点：
- 保留 `_create_client` 方法作为回退创建逻辑
- 缓存访问用 `asyncio.Lock` 保护
- `clear_semaphore_cache()` 同步清理客户端缓存
- `_get_cached_client` 中若客户端不在缓存，调用 `_create_client` 创建并存入

- [ ] **步骤 1：编写测试**

```python
# tests/test_chat.py（新建）
import asyncio

import pytest

from app.models.chat import _get_cached_client, close_client_cache, clear_semaphore_cache
from app.models.settings import LLMProviderConfig
from app.models.types import ProviderConfig as PCfg


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_semaphore_cache()
    yield
    clear_semaphore_cache()


@pytest.mark.asyncio
async def test_cached_client_reuse():
    """同 base_url+api_key 返回同一 AsyncOpenAI 实例"""
    provider = LLMProviderConfig(provider=PCfg(model="m", base_url="http://x", api_key="k"), concurrency=4)
    c1 = await _get_cached_client(provider)
    c2 = await _get_cached_client(provider)
    assert c1 is c2


@pytest.mark.asyncio
async def test_cached_client_different_keys():
    """不同 api_key 返回不同实例"""
    p1 = LLMProviderConfig(provider=PCfg(model="m", base_url="http://x", api_key="k1"), concurrency=4)
    p2 = LLMProviderConfig(provider=PCfg(model="m", base_url="http://x", api_key="k2"), concurrency=4)
    c1 = await _get_cached_client(p1)
    c2 = await _get_cached_client(p2)
    assert c1 is not c2
```

- [ ] **步骤 2：运行测试验证失败**

```bash
uv run pytest tests/test_chat.py -v
```
预期：FAIL（`_get_cached_client` / `close_client_cache` 未定义）

- [ ] **步骤 3：实现代码**

在 `chat.py` 中：
1. 模块级加 `_client_cache: dict[tuple[str, str], openai.AsyncOpenAI] = {}` 和 `_client_cache_lock = asyncio.Lock()`
2. 新增 `async def _get_cached_client(provider: LLMProviderConfig) -> openai.AsyncOpenAI`
3. 新增 `async def close_client_cache() -> None`
4. `generate()` 和 `generate_stream()` 中改用 `client = await _get_cached_client(provider)` 替代 `async with self._create_client(provider) as client`

- [ ] **步骤 4：运行测试验证通过**

```bash
uv run pytest tests/test_chat.py -v
```
预期：PASS

- [ ] **步骤 5：验证现有测试未退化**

```bash
uv run pytest tests/ -x -k "not llm and not embedding and not integration" --timeout=60
```
预期：PASS

- [ ] **步骤 6：Commit**

```bash
git add app/models/chat.py tests/test_chat.py
git commit -m "perf(chat): cache AsyncOpenAI clients per provider instead of creating per request"
```

---

## 任务 4：Embedding 批量大小打通（Fix 1）

**文件：**
- 修改：`app/models/embedding.py`
- 修改：`app/memory/embedding_client.py`
- 修改：`app/memory/memory_bank/lifecycle.py`

**接口与思路：**
1. `EmbeddingModel.__init__` 加 `batch_size: int = 32` 参数
2. `batch_encode()` 中用 `self._batch_size` 替代模块级 `_BATCH_SIZE`
3. `get_cached_embedding_model()` 加 `embedding_batch_size: int = 32` 参数，构造时传入
4. `EmbeddingClient.__init__` 加 `batch_size: int = 32` 参数，透传：`self._model.batch_size = batch_size`（或构造时传入）
5. `MemoryLifecycle` 中构造 `EmbeddingClient` 时传入 `config.embedding_batch_size`

由于 `EmbeddingModel` 是缓存的单例，多个调用者可能设不同 batch_size。当前唯一消费者是 MemoryBank，无冲突。

- [ ] **步骤 1：编写测试**

```python
# tests/test_embedding.py (新建或扩展现有)

def test_embedding_model_uses_batch_size():
    """EmbeddingModel 接受 batch_size 参数并存储"""
    from app.models.embedding import EmbeddingModel
    from app.models.types import ProviderConfig
    
    config = ProviderConfig(model="test", base_url="http://x", api_key="k")
    model = EmbeddingModel(provider=config, batch_size=50)
    assert model._batch_size == 50

def test_embedding_model_default_batch_size():
    """默认 batch_size 为 32"""
    from app.models.embedding import EmbeddingModel
    from app.models.types import ProviderConfig
    
    config = ProviderConfig(model="test", base_url="http://x", api_key="k")
    model = EmbeddingModel(provider=config)
    assert model._batch_size == 32
```

- [ ] **步骤 2：实现代码**

1. `embedding.py`：`EmbeddingModel.__init__` 加 `batch_size: int = 32`，存 `self._batch_size`；`batch_encode()` 中 `self._batch_size` 替代 `_BATCH_SIZE`；`get_cached_embedding_model()` 加参数
2. `embedding_client.py`：`EmbeddingClient.__init__` 加 `batch_size: int = 32`，初始化后设 `self._model._batch_size = batch_size`
3. `lifecycle.py`：构造 `EmbeddingClient` 处传入 `config.embedding_batch_size`

- [ ] **步骤 3：验证**

```bash
uv run pytest tests/ -x -k "not llm and not embedding and not integration" --timeout=60
uv run ruff check --fix && uv run ruff format && uv run ty check
```
预期：全部通过

- [ ] **步骤 4：Commit**

```bash
git add app/models/embedding.py app/memory/embedding_client.py app/memory/memory_bank/lifecycle.py tests/
git commit -m "perf(embedding): wire MemoryBankConfig.embedding_batch_size to EmbeddingModel"
```

---

## 任务 5：FAISS 索引类型可配置（Fix 7）

**文件：**
- 修改：`app/memory/memory_bank/index.py`

**接口与思路：**
`FaissIndex.__init__` 接收 `index_type` 和 `ivf_nlist` 参数。`_build_index()` 根据 `index_type` 选择 `IndexFlatIP` 或 `IndexIVFFlat`。默认 `"flat"`（当前行为不变）。

实现骨架：
```python
def _build_index(self) -> None:
    if self._index_type == "ivf_flat":
        quantizer = faiss.IndexFlatIP(self._dim)
        self._index = faiss.IndexIDMap(faiss.IndexIVFFlat(quantizer, self._dim, self._ivf_nlist))
        self._needs_train = True
    else:
        self._index = faiss.IndexIDMap(faiss.IndexFlatIP(self._dim))
        self._needs_train = False
```

注意：`_build_index` 是现有方法（约在 `index.py` 中部），需改为读取 `self._index_type` 等属性。`FaissIndex.__init__` 需从 `MemoryBankStore` 接收 config 的 `index_type` 和 `ivf_nlist`。

- [ ] **步骤 1：实现**

1. `FaissIndex.__init__` 加参数 `index_type: str = "flat"` 和 `ivf_nlist: int = 128`
2. `_build_index()` 按上述骨架实现
3. `store.py` 中 `FaissIndex(user_dir, self._config.embedding_dim)` → `FaissIndex(user_dir, self._config.embedding_dim, index_type=self._config.index_type, ivf_nlist=self._config.ivf_nlist)`
4. 文档字符串加说明

- [ ] **步骤 2：验证**

```bash
uv run pytest tests/test_index_recovery.py -v --timeout=60
```
预期：PASS（索引恢复测试仍通过）

- [ ] **步骤 3：Commit**

```bash
git add app/memory/memory_bank/index.py app/memory/memory_bank/store.py
git commit -m "feat(index): add configurable index type (flat/ivf_flat), default flat"
```

---

## 任务 6：检索管道增强（Fixes 4, 5, 6）

**文件：**
- 修改：`app/memory/memory_bank/retrieval.py`
- 修改：`app/memory/memory_bank/store.py`（BM25 失效标记调用点）

**前置确认**：`RetrievalPipeline.__init__` 接收 `index: IndexReader` 参数并存储为 `self._index`。`IndexReader` 协议包含 `get_metadata() → list[dict]` 方法。BM25 索引重建通过 `self._index.get_metadata()` 获取全量文本语料。

**接口与思路：**
在 `RetrievalPipeline` 中增加三项功能：

**Fix 4（strength 上限）**：`_update_memory_strengths()` 中 `new_strength = min(existing + 1.0, config.max_memory_strength)`。移除注释中的"不再设上限"。

**Fix 5（保留率加权）**：在 `_apply_speaker_filter()` 之后、`[:top_k]` 截断之前，插入 `_apply_retention_weighting()` 方法。算法见规格文档。

**Fix 6（BM25 回退）**：`RetrievalPipeline` 维持 `_bm25_index` 和 `_bm25_corpus`。FAISS 粗排后若最高分 < threshold 且启用回退，执行 BM25 检索并与 FAISS 结果合并。

BM25 回退实现骨架：
```python
async def _bm25_fallback(self, query: str, top_k: int) -> list[dict]:
    from rank_bm25 import BM25Okapi
    if self._bm25_index is None:
        self._rebuild_bm25_index()
    tokenized_query = query.lower().split()
    scores = self._bm25_index.get_scores(tokenized_query)
    # 取 top_k 索引，构建结果 dict
    ...

def _rebuild_bm25_index(self) -> None:
    from rank_bm25 import BM25Okapi
    metadata = self._index.get_metadata()
    self._bm25_corpus = [m.get("text", "") for m in metadata if not m.get("forgotten")]
    tokenized = [text.lower().split() for text in self._bm25_corpus]
    self._bm25_index = BM25Okapi(tokenized)
```

保留率加权的 `_apply_retention_weighting` 需从 `forget.py` 导入 `forgetting_retention`。

- [ ] **步骤 1：编写测试**

在 `tests/test_retrieval_pipeline.py` 中新增：

```python
def test_strength_capped_at_max(mock_index, mock_embedding):
    """memory_strength 不超过 max_memory_strength"""
    config = MemoryBankConfig(max_memory_strength=5)
    pipeline = RetrievalPipeline(mock_index, mock_embedding, config)
    mock_index.total = 10
    metadata = [
        {"faiss_id": 0, "text": "t", "source": "d", "speakers": ["A"],
         "memory_strength": 5, "forgotten": False}
    ]
    mock_index.get_metadata.return_value = metadata
    mock_index.search = AsyncMock(return_value=[
        {"faiss_id": 0, "text": "t", "source": "d", "score": 0.9,
         "_meta_idx": 0, "speakers": ["A"], "forgotten": False}
    ])
    _, updated = await pipeline.search("query")
    # strength 5 already at max, should not increase
    assert metadata[0]["memory_strength"] == 5


def test_retention_weighting_applied(mock_index, mock_embedding):
    """保留率加权后低 retention 条目排位下降"""
    config = MemoryBankConfig(retrieval_alpha=0.7)
    pipeline = RetrievalPipeline(mock_index, mock_embedding, config)
    # 构造两条命中：A 高分高 retention, B 低分但新鲜
    mock_index.total = 10
    metadata = [
        {"faiss_id": 0, "text": "old", "source": "d1", "speakers": ["A"],
         "memory_strength": 1, "last_recall_date": "2020-01-01", "forgotten": False},
        {"faiss_id": 1, "text": "new", "source": "d2", "speakers": ["A"],
         "memory_strength": 5, "last_recall_date": "2026-05-10", "forgotten": False},
    ]
    mock_index.get_metadata.return_value = metadata
    mock_index.search = AsyncMock(return_value=[
        {"faiss_id": 0, "text": "old", "source": "d1", "score": 0.85,
         "_meta_idx": 0, "speakers": ["A"], "forgotten": False},
        {"faiss_id": 1, "text": "new", "source": "d2", "score": 0.8,
         "_meta_idx": 1, "speakers": ["A"], "forgotten": False},
    ])
    results, _ = await pipeline.search("query", top_k=2, reference_date="2026-05-10")
    # 新鲜条目应因 retention 加权排到前面
    assert results[0].get("text") == "new"
```

- [ ] **步骤 2：运行测试验证失败**

```bash
uv run pytest tests/test_retrieval_pipeline.py -k "strength_capped or retention_weighting" -v
```
预期：FAIL（功能未实现）

- [ ] **步骤 3：实现代码**

1. 修改 `_update_memory_strengths`：加 `max_strength` 参数，clamp
2. 新增 `_apply_retention_weighting` 方法
3. 修改 `search()`：在 speaker filter 后调 `_apply_retention_weighting`，重排序
4. 新增 `_bm25_fallback` 方法
5. 修改 `search()`：在 FAISS 搜索后检查阈值，触发 BM25 回退
6. 新增 `invalidate_bm25()` 方法。在 `store.py` 的 `_lifecycle.write*` 系列调用后调用 `self._retrieval.invalidate_bm25()`（store.py 已有 `self._retrieval` 引用）

- [ ] **步骤 4：运行测试验证通过**

```bash
uv run pytest tests/test_retrieval_pipeline.py -v --timeout=60
```
预期：全部 PASS

- [ ] **步骤 5：Commit**

```bash
git add app/memory/memory_bank/retrieval.py app/memory/memory_bank/store.py tests/test_retrieval_pipeline.py
git commit -m "feat(retrieval): add strength cap, retention-weighted scoring, BM25 fallback"
```

---

## 任务 7：_source_event_index 磁盘缓存（Fix 8）

**文件：**
- 修改：`app/memory/memory_bank/store.py`

**接口与思路：**
在 `_ensure_loaded()` 中加载 `memorybank/source_event_index.json`。在 `_maybe_save()` 和 `close()` 中写入。损坏 JSON 时回退到 metadata 全量扫描（现有行为）。

实现骨架：
```python
_SOURCE_INDEX_FILENAME = "source_event_index.json"

async def _load_source_index(self) -> None:
    path = self._user_dir / _SOURCE_INDEX_FILENAME
    if path.exists():
        try:
            self._source_event_index = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            self._source_event_index = {}

async def _save_source_index(self) -> None:
    if not self._source_index_dirty:
        return
    path = self._user_dir / _SOURCE_INDEX_FILENAME
    path.write_text(json.dumps(self._source_event_index, ensure_ascii=False))
    self._source_index_dirty = False
```

- [ ] **步骤 1：编写测试**

```python
# tests/test_memory_bank.py 中新增

def test_source_event_index_save_load(tmp_path):
    """source_event_index 可序列化/反序列化"""
    import json
    index_path = tmp_path / "source_event_index.json"
    data = {"2026-05-10": ["id1", "id2"], "2026-05-09": ["id3"]}
    index_path.write_text(json.dumps(data))
    loaded = json.loads(index_path.read_text())
    assert loaded == data
```

- [ ] **步骤 2：实现代码**

1. `__init__` 中 `_source_index_dirty = False`
2. `_ensure_loaded()` 中调用 `_load_source_index()`
3. `write()` / `write_batch()` 中置 `_source_index_dirty = True`
4. `_maybe_save()` 中调用 `_save_source_index()`
5. `close()` 中调用 `_save_source_index()`

- [ ] **步骤 3：验证**

```bash
uv run pytest tests/test_memory_bank.py -v -x --timeout=60
```
预期：PASS

- [ ] **步骤 4：Commit**

```bash
git add app/memory/memory_bank/store.py tests/test_memory_bank.py
git commit -m "perf(memory): persist _source_event_index to disk to avoid O(n) rebuild on restart"
```

---

## 任务 8：rules + workflow + ablation_runner 清理（Fixes 3, 10）

**文件：**
- 修改：`app/agents/rules.py`
- 修改：`app/agents/workflow.py`
- 修改：`experiments/ablation/ablation_runner.py`

**接口与思路：**

**Fix 3（消融标记模块化）**：
- `rules.py`：加 `_ablation_disable_rules = False`，公开 `set_ablation_disable_rules(v)`。`postprocess_decision()` 读 `_ablation_disable_rules` 而非 `os.getenv`
- `workflow.py`：加 `_ablation_disable_feedback = False`，公开 `set_ablation_disable_feedback(v)`。`_strategy_node()` 读 `_ablation_disable_feedback` 而非 `os.getenv`
- `ablation_runner.py`：`run_variant()` 中调用 `set_ablation_disable_rules(True)` 替代 `os.environ[...]="1"`。`run_variant()` 中 `run_agent_workflow()` 前根据 variant 调对应 setter。`_restore_env()` 中移除 ABLATION_DISABLE_* 恢复

**Fix 10（fatigue_threshold 缓存）**：
- `rules.py`：加 `_cached_fatigue_threshold: float | None = None`。`_get_fatigue_threshold()` 先查缓存

注意 `_ablation_disable_rules` 和 `_ablation_disable_feedback` 的初始值从 env 读取一次：
```python
_ablation_disable_rules: bool = bool(int(os.getenv("ABLATION_DISABLE_RULES", "0")))
```

- [ ] **步骤 1：编写测试**

```python
# tests/test_rules.py 中新增

def test_disable_rules_skips_postprocess():
    from app.agents.rules import set_ablation_disable_rules, postprocess_decision
    set_ablation_disable_rules(True)
    decision = {"should_remind": True, "reminder_content": "test"}
    ctx = {"scenario": "highway"}
    result, mods = postprocess_decision(decision, ctx)
    assert result is decision  # 不修改
    set_ablation_disable_rules(False)  # 恢复

def test_fatigue_threshold_cached(monkeypatch):
    from app.agents.rules import _get_fatigue_threshold, reset_fatigue_threshold_cache
    reset_fatigue_threshold_cache()
    monkeypatch.setenv("FATIGUE_THRESHOLD", "0.85")
    first = _get_fatigue_threshold()
    monkeypatch.setenv("FATIGUE_THRESHOLD", "0.5")  # 改 env，缓存不变
    second = _get_fatigue_threshold()
    assert first == second == 0.85
    reset_fatigue_threshold_cache()
```

- [ ] **步骤 2：运行测试验证失败**

```bash
uv run pytest tests/test_rules.py -k "disable_rules_skips or fatigue_threshold_cached" -v
```
预期：FAIL（功能未实现）

- [ ] **步骤 3：实现代码**

**rules.py**：
1. 模块级 `_ablation_disable_rules = bool(int(os.getenv("ABLATION_DISABLE_RULES", "0")))`
2. `def set_ablation_disable_rules(v: bool) -> None: global _ablation_disable_rules; _ablation_disable_rules = v`
3. `postprocess_decision()` 中用 `if _ablation_disable_rules:` 替代 `if os.getenv(...)`
4. `_cached_fatigue_threshold: float | None = None`
5. `_get_fatigue_threshold()` 先查缓存，未命中读 env
6. `def reset_fatigue_threshold_cache() -> None`

**workflow.py**：
1. 模块级 `_ablation_disable_feedback = bool(int(os.getenv("ABLATION_DISABLE_FEEDBACK", "0")))`
2. `def set_ablation_disable_feedback(v: bool) -> None`
3. `_strategy_node()` 中用 `if _ablation_disable_feedback:` 替代 `if os.getenv(...)`

**ablation_runner.py**：
1. import `set_ablation_disable_rules`, `set_ablation_disable_feedback`
2. `run_variant()` 中根据 variant 调用对应 setter
3. `_restore_env()` 中移除 `ABLATION_DISABLE_RULES` 和 `ABLATION_DISABLE_FEEDBACK` 的恢复

- [ ] **步骤 4：运行测试验证通过**

```bash
uv run pytest tests/test_rules.py tests/test_shortcuts.py -v --timeout=60
```
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add app/agents/rules.py app/agents/workflow.py experiments/ablation/ablation_runner.py tests/test_rules.py
git commit -m "perf(agents): replace hot-path os.getenv with module-level ablation flags; cache fatigue threshold"
```

---

## 任务 9：exportData 遍历优化（Fix 9）

**文件：**
- 修改：`app/api/resolvers/mutation.py`

**接口与思路：**
`export_data()` 中 `u_dir.rglob("*")` 改为按后缀分别 `rglob`，天然排除 `index.faiss` 等二进制文件。

```python
for suffix in (".jsonl", ".toml", ".json"):
    for fpath in u_dir.rglob(f"*{suffix}"):
        if "memorybank" in fpath.parts:
            continue
        ...
```

- [ ] **步骤 1：实现代码**

在 `mutation.py:238`，将 `for fpath in u_dir.rglob("*"):` 替换为双层循环。

- [ ] **步骤 2：验证现有测试通过**

```bash
uv run pytest tests/test_graphql.py -v -x --timeout=60
```
预期：PASS

- [ ] **步骤 3：Commit**

```bash
git add app/api/resolvers/mutation.py
git commit -m "perf(api): optimize exportData rglob to exclude binary files by suffix"
```

---

## 收尾任务：全量回归

- [ ] **步骤 1：运行全量测试**

```bash
uv run pytest tests/ -v --timeout=60
```
预期：292+ passed, 0 failed

- [ ] **步骤 2：运行 lint + typecheck**

```bash
uv run ruff check --fix && uv run ruff format --check && uv run ty check
```
预期：全部通过

- [ ] **步骤 3：Commit（如有 fixup）**

```bash
git add -A && git commit -m "chore: fix lint/type issues after optimization patch"
```
