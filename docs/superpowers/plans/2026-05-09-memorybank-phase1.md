# MemoryBank 四阶段架构改造 实现计划

> **面向 AI 代理的工作者：** 按任务序号顺序执行。步骤用复选框（`- [ ]`）跟踪进度。每任务完成后 commit。

**目标：** 对 MemoryBank 进行四阶段改造：多用户隔离、错误处理统一、配置集中、索引恢复降级、性能优化、功能增强、测试覆盖、可观测性。

**架构：** 构造时绑定用户（`MemoryModule` → per-user `MemoryBankStore` → `FaissIndex` 子目录隔离）；异常体系（`exceptions.py` 三层）；`MemoryBankConfig` 集中全部参数；`LoadResult` 降级加载；批量嵌入编码；缓存 + 节流 I/O。

**技术栈：** Python 3.14, FAISS, pydantic-settings, pytest-asyncio

---

### 任务 1：新增异常体系

**文件：**
- 创建：`app/memory/exceptions.py`

- [ ] **步骤 1：创建 exceptions.py**

```python
"""MemoryBank 异常体系——三层：基类 → 瞬态/永久 → 具体。"""


class MemoryBankError(Exception):
    """MemoryBank 异常基类。"""


class TransientError(MemoryBankError):
    """可重试的瞬态错误（网络、超时、限速）。"""

    def __init__(self, message: str, retry_after: float = 1.0) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class FatalError(MemoryBankError):
    """不可恢复的永久错误（配置、数据损坏）。"""


class LLMCallFailed(TransientError):
    """LLM 调用失败（可重试）。"""


class EmbeddingFailed(TransientError):
    """嵌入 API 调用失败（可重试）。"""


class SummarizationEmpty(MemoryBankError):
    """LLM 返回空内容——非错误，哨兵异常。调用方捕获后返回 None。"""


class ConfigError(FatalError):
    """配置错误。"""


class MetadataCorrupted(FatalError):
    """元数据损坏，不可自动恢复。"""


class IndexIntegrityError(FatalError):
    """FAISS 索引文件损坏，不可读取。"""
```

- [ ] **步骤 2：验证语法**

`uv run python -c "from app.memory.exceptions import LLMCallFailed, SummarizationEmpty"`

- [ ] **步骤 3：Commit**

```bash
git add app/memory/exceptions.py
git commit -m "feat: add MemoryBank exception hierarchy"
```

---

### 任务 2：扩展 MemoryBankConfig

**文件：**
- 修改：`app/memory/memory_bank/config.py`

接口：
- 挪入 `llm.py`/`forget.py` 中的模块常量
- 新增 `llm_*` 字段、`embedding_batch_size`、`save_interval_seconds`、`reference_date_auto`
- 改 `soft_forget_threshold` 默认值 0.15 → 0.3

思路：
- 保留现有字段，在对应分组注释下追加新字段
- `llm_anchor_user`/`llm_anchor_assistant` 从当前 `llm.py` 的 `_ANCHOR_USER`/`_ANCHOR_ASSISTANT` 字符串复制
- `llm_temperature`/`llm_max_tokens` 默认 None（透气传 ChatModel 默认值）
- `embedding_batch_size` 默认 100
- `save_interval_seconds` 默认 30.0
- `reference_date_auto` 默认 False
- 加 `field_validator`：`save_interval_seconds > 0`、`embedding_batch_size > 0`

- [ ] **步骤 1：修改 config.py**

更新文件，追加所有新字段并调整遗忘阈值。具体代码见规格第三节 `MemoryBankConfig` 完整定义。

- [ ] **步骤 2：验证字段可导入**

`uv run python -c "from app.memory.memory_bank.config import MemoryBankConfig; c=MemoryBankConfig(); print(c.embedding_batch_size, c.llm_max_retries)"` → 100, 3

- [ ] **步骤 3：Commit**

```bash
git add app/memory/memory_bank/config.py
git commit -m "feat: expand MemoryBankConfig with all parameters"
```

---

### 任务 3：改造 FaissIndex — LoadResult + reference_date + 降级恢复

**文件：**
- 修改：`app/memory/memory_bank/index.py`

接口：
- `load()` 返回 `LoadResult` 而非 `None`
- 新增 `compute_reference_date(offset_days)` 方法
- 损坏时降级恢复（不删 metadata 骨架，备份 index.bak）

思路：
- 定义 `LoadResult = namedtuple("LoadResult", ["ok", "warnings", "recovery_actions"])`
- `load()` 内部：当前 `return`（损坏）改为 `return LoadResult(ok=False, warnings=[...], recovery_actions=[...])`；正常返回 `LoadResult(ok=True, warnings=[], recovery_actions=[])`
- metadata 损坏但 index 正常时：不从 `return` 提前退出——继续从 index.ntotal 生成骨架 metadata 条目，标记 `corrupted=True`
- index 损坏时：`shutil.copy` 到 `.bak` 再删
- `compute_reference_date`：遍历 self._metadata 找最大 timestamp[:10]，返回 date + timedelta(days=offset_days)

- [ ] **步骤 1：添加 namedtuple 和改造 load()**

见规格第四节降级逻辑要点。

- [ ] **步骤 2：添加 compute_reference_date**

```python
from datetime import date, datetime, timedelta, UTC

def compute_reference_date(self, offset_days: int = 1) -> str:
    max_ts = max((m.get("timestamp", "")[:10] for m in self._metadata), default="")
    if not max_ts:
        return datetime.now(UTC).strftime("%Y-%m-%d")
    return (date.fromisoformat(max_ts) + timedelta(days=offset_days)).strftime("%Y-%m-%d")
```

- [ ] **步骤 3：验证**

`uv run python -c "from app.memory.memory_bank.index import FaissIndex, LoadResult; print(LoadResult)"` → 类可见

- [ ] **步骤 4：Commit**

```bash
git add app/memory/memory_bank/index.py
git commit -m "feat: add LoadResult, compute_reference_date, degraded index recovery"
```

---

### 任务 4：改造 LlmClient — 配置化 + 异常化

**文件：**
- 修改：`app/memory/memory_bank/llm.py`

接口：
- `call(prompt, *, system_prompt, **kwargs) -> str`（抛异常，不返 None）
- 构造函数收 `config: MemoryBankConfig`
- 删除模块常量（`LLM_MAX_RETRIES` 等），改用 config 字段
- 瞬态错误抛 `LLMCallFailed`；空结果抛 `SummarizationEmpty`；不可重试非瞬态记录日志后抛 `LLMCallFailed`

思路：
- 构造函数新增 `config` 参数
- `call()` 返回类型 `-> str`
- 重试循环中：context exceeded → 截断 prompt；transient → 指数退避；成功但内容为空 → `raise SummarizationEmpty()`；重试耗尽 → `raise LLMCallFailed(msg)`
- `system_prompt` 从参数取（不硬编码）
- 锚定消息从 `config.llm_anchor_user/assistant` 取

- [ ] **步骤 1：改造 LlmClient**

修改文件：
1. 导入 exceptions
2. 构造函数加 `config` 参数
3. `call()` 签名改为 `-> str`，内部所有 `return None` 改为抛异常
4. 模块常量引用改为 `self._config.xxx`

- [ ] **步骤 2：验证导入无循环依赖**

`uv run python -c "from app.memory.memory_bank.llm import LlmClient"`

- [ ] **步骤 3：Commit**

```bash
git add app/memory/memory_bank/llm.py
git commit -m "feat: config-based LlmClient with typed exceptions"
```

---

### 任务 5：改造 ForgetCurve — 配置化 + reference_date_auto

**文件：**
- 修改：`app/memory/memory_bank/forget.py`

接口：
- `forgetting_retention()` 签名不变，但模块常量 `FORGETTING_TIME_SCALE` → 由调用方传入
- `compute_ingestion_forget_ids()` 使用 `config.forgetting_time_scale`（已由调用方传入 config）
- `ForgettingCurve` 不变（已收 config）
- `compute_ingestion_forget_ids` 静默 `return []` 改为记录 warning

思路：
- 删除模块级 `FORGETTING_TIME_SCALE` 常量。`forgetting_retention` 默认 time_scale=1.0，现有两调用方（`compute_ingestion_forget_ids` 通过 config、`ForgettingCurve.maybe_forget` 通过 self._config）均已显式传值，无行为变化
- `compute_ingestion_forget_ids` 的 except 块加 warning

- [ ] **步骤 1：改 forget.py**

1. 删 `FORGETTING_TIME_SCALE`
2. `forgetting_retention()` 默认 time_scale=1.0
3. `compute_ingestion_forget_ids` 的 except 块加 warning

- [ ] **步骤 2：验证**

`uv run python -c "from app.memory.memory_bank.forget import forgetting_retention; print(forgetting_retention(10, 5))"`

- [ ] **步骤 3：Commit**

```bash
git add app/memory/memory_bank/forget.py
git commit -m "refactor: config-driven forgetting with warning on corrupted entries"
```

---

### 任务 6：改造 Summarizer — 异常体系 + LLM 参数

**文件：**
- 修改：`app/memory/memory_bank/summarizer.py`

接口：
- 四个 `get_*` 方法：调用 `LlmClient.call()`，捕获 `SummarizationEmpty` → 返回 None；`LLMCallFailed` → 上抛
- 调用 `LlmClient.call()` 时传入 `temperature=0.3, max_tokens=400`

思路：
- 每个 `get_*` 方法从 `result = await self._llm.call(...)` 改为 try/except：
  ```python
  try:
      result = await self._llm.call(prompt, system_prompt=..., temperature=0.3, max_tokens=400)
  except SummarizationEmpty:
      return None  # 或其他哨兵处理
  # LLMCallFailed 不捕获，上抛到 lifecycle._background_summarize
  ```
- 提示词不变

- [ ] **步骤 1：改 summarizer.py**

改四个方法的 LLM 调用处。

- [ ] **步骤 2：验证**

`uv run python -c "from app.memory.memory_bank.summarizer import Summarizer"` → 无 ImportError

- [ ] **步骤 3：Commit**

```bash
git add app/memory/memory_bank/summarizer.py
git commit -m "refactor: Summarizer uses exception-based LLM calls with explicit params"
```

---

### 任务 7：改造 lifecycle.py — 异常体系 + 批量嵌入 + 埋点

**文件：**
- 修改：`app/memory/memory_bank/lifecycle.py`

接口：
- `write()` 中嵌入调用从逐对 `encode()` 改为批量 `encode_batch()`
- `_background_summarize` 异常处理改为捕获 `SummarizationEmpty`（正常）和 `TransientError`（日志告警）
- `_forget_at_ingestion` 加 `reference_date_auto` 路径
- 加指标埋点（search 路径不在此文件，仅 write/summarize/forget 相关）

思路：
- `write()`：收集 `pair_texts` 列表 → 一次 `encode_batch()` → 逐 `add_vector()`
- `_forget_at_ingestion`：`today = self._config.reference_date or (self._index.compute_reference_date() if self._config.reference_date_auto else datetime.now(UTC)...)`
- `_background_summarize`：try/except 替代裸 except
- 埋点：`write()` 中 embedding 调用前后记录 `embedding_latency_ms`；`_background_summarize` 异常路径 `background_task_failures += 1`；`purge_forgotten()` 后 `forget_count += 1`、`forget_removed_count += len(forgotten_ids)`

- [ ] **步骤 1：改 write() 批量嵌入**

重构 `write()` 方法：先收集再批量。

- [ ] **步骤 2：改异常处理 + reference_date_auto**

改 `_forget_at_ingestion` 和 `_background_summarize`。

- [ ] **步骤 3：验证**

`uv run python -c "from app.memory.memory_bank.lifecycle import MemoryLifecycle"` → 无 ImportError

- [ ] **步骤 4：Commit**

```bash
git add app/memory/memory_bank/lifecycle.py
git commit -m "feat: batch embeddings, auto reference_date, exception handling in lifecycle"
```

---

### 任务 8：改造 retrieval.py — 分块缓存 + 埋点

**文件：**
- 修改：`app/memory/memory_bank/retrieval.py`

接口：
- `RetrievalPipeline` 加 `_cached_chunk_size`/`_cached_metadata_len`，`_get_chunk_size` 改为缓存版（长度不变则直接返回）
- `search()` 加指标埋点（search_count、latency、empty_count）

思路：
- 将 `_get_effective_chunk_size` 调用替换为 `self._get_chunk_size(metadata, self._config)`
- 新增 `_get_chunk_size` 方法（规格阶段二 5 节代码）
- `search()` 入口记录时间，出口记录 latency；若 returns `[], False` → empty_count+1

- [ ] **步骤 1：加缓存 + 埋点**

修改 `RetrievalPipeline`：新增 `_get_chunk_size`，`search()` 前后加埋点。

- [ ] **步骤 2：验证**

`uv run python -c "from app.memory.memory_bank.retrieval import RetrievalPipeline"` → 无 ImportError

- [ ] **步骤 3：Commit**

```bash
git add app/memory/memory_bank/retrieval.py
git commit -m "perf: cache chunk_size, add search metrics"
```

---

### 任务 9：新增 observability.py

**文件：**
- 创建：`app/memory/memory_bank/observability.py`

接口：
- `MemoryBankMetrics` 数据类，含 count/latency 字段，`snapshot()`/`reset()` 方法
- 延迟字段用 `field(default_factory=list)`，无需环形缓冲（deque 引入额外复杂度，100 条够用）

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MemoryBankMetrics:
    search_count: int = 0
    search_empty_count: int = 0
    search_latency_ms: list[float] = field(default_factory=list)
    embedding_latency_ms: list[float] = field(default_factory=list)
    forget_count: int = 0
    forget_removed_count: int = 0
    background_task_failures: int = 0
    index_load_warnings: list[str] = field(default_factory=list)
    store_instance_count: int = 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "search_count": self.search_count,
            "search_empty_ratio": (
                self.search_empty_count / self.search_count
                if self.search_count > 0
                else 0
            ),
            "search_latency_p50_ms": _p50(self.search_latency_ms),
            "search_latency_p90_ms": _p90(self.search_latency_ms),
            "forget_count": self.forget_count,
            "forget_removed_count": self.forget_removed_count,
            "background_task_failures": self.background_task_failures,
            "index_load_warnings": self.index_load_warnings[-10:],
            "store_instance_count": self.store_instance_count,
        }

    def reset(self) -> None:
        self.search_count = 0
        self.search_empty_count = 0
        self.forget_count = 0
        self.forget_removed_count = 0
        self.background_task_failures = 0
        self.index_load_warnings.clear()
```

- [ ] **步骤 1：创建 observability.py**

写入上述代码。辅助函数 `_p50`/`_p90` 内部实现（sorted + index）。

- [ ] **步骤 2：验证**

`uv run python -c "from app.memory.memory_bank.observability import MemoryBankMetrics; m=MemoryBankMetrics(); print(m.snapshot())"`

- [ ] **步骤 3：Commit**

```bash
git add app/memory/memory_bank/observability.py
git commit -m "feat: add MemoryBank observability metrics"
```

---

### 任务 10：改造 store.py — 多用户构造 + LoadResult + 持久化降频 + format_search_results + metrics

**文件：**
- 修改：`app/memory/memory_bank/store.py`

接口：
- `__init__` 加 `user_id` 参数，拼 `user_dir = data_dir / f"user_{user_id}"`
- 初始化时消费 `LoadResult`（若 `ok=False` 则 logger.warning 相应信息）
- 新增 `_maybe_save()`（30s 节流）
- `search()` 改用 `_maybe_save()`；加 corrupted 条目过滤
- 新增 `format_search_results(query, top_k) -> str`
- 新增 `metrics` 属性（返回 `MemoryBankMetrics` 实例）

思路：
- `__init__` 中 `self._index = FaissIndex(user_dir, ...)` 后调用 `load_result = await self._index.load()`，处理 warnings
- `self._metrics = MemoryBankMetrics()`
- `_maybe_save` 用 `time.monotonic()` 计时
- `search()` 结果构建 `SearchResult` 前过滤 `m.get("corrupted")` 条目
- `format_search_results`：调 `search()` → 按 source 分组 → 输出 `[memory_strength=N] [date=YYYY-MM-DD] text` 格式

- [ ] **步骤 1：改 __init__ + LoadResult + _maybe_save**

1. 构造函数签名加 `user_id: str = "default"`
2. 组装 `user_dir`
3. load 后处理 LoadResult
4. 添加 `_maybe_save`

- [ ] **步骤 2：改 search() + format_search_results + metrics**

1. search 中 corrupted 过滤 + `_maybe_save()`
2. 新增 `format_search_results`

- [ ] **步骤 3：验证**

`uv run python -c "from app.memory.memory_bank.store import MemoryBankStore"` → 无 ImportError

- [ ] **步骤 4：Commit**

```bash
git add app/memory/memory_bank/store.py
git commit -m "feat: multi-user isolation, throttled persistence, format_search_results, metrics"
```

---

### 任务 11：改造 memory.py — store 注册表

**文件：**
- 修改：`app/memory/memory.py`

接口：
- `MemoryModule` 加 `_stores: dict[str, MemoryBankStore]`
- `get_store(user_id) -> MemoryBankStore` 懒初始化
- `close()` 遍历关闭所有 store

思路：
- 现有 `MemoryModule.__init__` 中 `self._stores = {}`
- `get_store` 逻辑见规格阶段一 MemoryModule 薄注册表
- `close()` 遍历 `self._stores.values()` 逐个 `close()`

- [ ] **步骤 1：改 memory.py**

添加注册表逻辑。注意：现有可能有直接构造 `MemoryBankStore` 的代码——保留向后兼容路径（`get_store("default")` 返回原 store）

- [ ] **步骤 2：验证**

`uv run python -c "from app.memory.memory import MemoryModule"` → 无 ImportError

- [ ] **步骤 3：Commit**

```bash
git add app/memory/memory.py
git commit -m "feat: add per-user store registry to MemoryModule"
```

---

### 任务 12：改 interfaces.py — 追加 close()

**文件：**
- 修改：`app/memory/interfaces.py`

- [ ] **步骤 1：加 close() 方法**

在 `MemoryStore` Protocol 末尾加 `async def close(self) -> None: ...`

- [ ] **步骤 2：验证**

`uv run python -c "from app.memory.interfaces import MemoryStore"` → 无 ImportError

- [ ] **步骤 3：Commit**

```bash
git add app/memory/interfaces.py
git commit -m "feat: add close() to MemoryStore Protocol"
```

---

### 任务 13：修复所有现有调用点（适配新签名）

**文件：**
- 检查所有引用 `LlmClient`、`MemoryBankStore` 构造的调用点

思路：
- 全局搜索 `LlmClient(`、`MemoryBankStore(`、`ForgettingCurve(`、`FaissIndex.load()`
- 适配新签名：LlmClient 需 config 参数；MemoryBankStore 需 user_id；FaissIndex.load() 返回值改为 LoadResult
- 需检查的文件：`store.py`（已改）、`lifecycle.py`（已改）、`summarizer.py`（已改）、可能的测试/GraphQL resolver

- [ ] **步骤 1：全局搜索并适配**

```bash
rg "LlmClient\(" app/ -l
rg "MemoryBankStore\(" app/ -l
rg "\.load\(\)" app/memory/ -l
```

逐文件检查签名匹配。

- [ ] **步骤 2：运行现有测试**

`uv run pytest tests/ -v --timeout=30 -x`

- [ ] **步骤 3：Commit**

```bash
git add -A
git commit -m "fix: adapt all call sites to new signatures"
```

---

### 任务 14：新增 test_index_recovery.py

**文件：**
- 创建：`tests/test_index_recovery.py`

接口：测试 FaissIndex 加载损坏文件的降级行为。

测试用例：
- `test_load_corrupted_metadata_rebuilds_skeleton` — metadata.json 内容为 `"garbage"`，验证 LoadResult.warnings 非空，index 仍可用
- `test_load_corrupted_index_backups_and_rebuilds` — index.faiss 内容为随机字节，验证 .bak 文件存在，新 index 为空
- `test_load_count_mismatch_adds_skeleton` — metadata 比 index 少条目，验证自动补齐

- [ ] **步骤 1：写测试**

每个 Given: 预置损坏文件 → When: `FaissIndex.load()` → Then: assert LoadResult + 检查文件/内存状态。

- [ ] **步骤 2：运行测试**

`uv run pytest tests/test_index_recovery.py -v`

- [ ] **步骤 3：Commit**

```bash
git add tests/test_index_recovery.py
git commit -m "test: add index recovery degraded mode tests"
```

---

### 任务 15：新增 test_multi_user.py

**文件：**
- 创建：`tests/test_multi_user.py`

接口：验证 per-user 数据隔离。

测试用例：
- `test_two_users_data_isolated` — 构造两个 MemoryBankStore（user_a/user_b），各写不同的 MemoryEvent，verify 互相 search 不应看到对方数据
- `test_store_close_cleans_up` — close() 后再 search 抛异常（或返回空）

- [ ] **步骤 1：写测试**

两个独立 store 实例（不同 user_dir），pytest tmp_path。

- [ ] **步骤 2：运行测试**

`uv run pytest tests/test_multi_user.py -v`

- [ ] **步骤 3：Commit**

```bash
git add tests/test_multi_user.py
git commit -m "test: add multi-user isolation tests"
```

---

### 任务 16：新增 test_forgetting.py

**文件：**
- 创建：`tests/test_forgetting.py`

接口：覆盖遗忘曲线和遗忘判定。

测试用例：
- `test_retention_zero_days_returns_one` — 0 天 → 1.0
- `test_retention_decay` — strength=1, days=1 → math.exp(-1)
- `test_deterministic_forget_below_threshold` — 留存率 < 0.3 → 标记 forgotten=True
- `test_deterministic_keep_above_threshold` — 留存率 >= 0.3 → 不变
- `test_probabilistic_mode_with_seed` — 固定 seed，概率模式，验证至少部分条目被遗忘
- `test_throttle_skips_second_call` — 两次 maybe_forget 间隔 < forget_interval → 第二次返回 None

- [ ] **步骤 1：写测试**

使用 `MemoryBankConfig` 实例（forget_mode="deterministic"/"probabilistic"）。

- [ ] **步骤 2：运行测试**

`uv run pytest tests/test_forgetting.py -v`

- [ ] **步骤 3：Commit**

```bash
git add tests/test_forgetting.py
git commit -m "test: add forgetting curve and threshold tests"
```

---

### 任务 17：新增 test_retrieval_pipeline.py

**文件：**
- 创建：`tests/test_retrieval_pipeline.py`

接口：mock FaissIndex + mock EmbeddingClient，验证四阶段管道。

测试用例：
- `test_empty_index_returns_empty` — ntotal=0 → []
- `test_single_result_no_neighbors` — 单条命中无邻居 → 1 条结果
- `test_merge_neighbors_same_source` — 同 source 连续 3 条，命中中间 → 合并为 1 条
- `test_speaker_filter_downweights` — query 含 "Alice"，结果 speakers=["Bob"] → score *0.75
- `test_speaker_filter_boost_negative_score` — query 含 "Alice"，结果 speakers=["Bob"]，原始 score=-0.5 → score=-0.625
- `test_overlap_deduplication` — 两条结果共享 metadata 索引 → 合并为 1

- [ ] **步骤 1：写 mock 和测试**

Mock IndexReader Protocol（提供 total/search/get_metadata 方法）和 mock EmbeddingClient（返回固定向量）。

- [ ] **步骤 2：运行测试**

`uv run pytest tests/test_retrieval_pipeline.py -v`

- [ ] **步骤 3：Commit**

```bash
git add tests/test_retrieval_pipeline.py
git commit -m "test: add retrieval pipeline unit tests"
```

---

### 任务 18：新增 test_summarizer.py

**文件：**
- 创建：`tests/test_summarizer.py`

接口：验证不可变保护和异常处理。

测试用例：
- `test_daily_summary_skips_when_exists` — metadata 已有 source="summary_2024-06-01" → `get_daily_summary` 返回 None（不调 LLM）
- `test_overall_summary_skips_when_exists` — extra["overall_summary"] 已存在 → 返回 None
- `test_summarization_empty_returns_none` — mock LLM 抛 SummarizationEmpty → 返回 None
- `test_llm_call_failed_propagates` — mock LLM 抛 LLMCallFailed → 上抛

- [ ] **步骤 1：写测试**

Mock LlmClient（返回固定文本或抛异常）。

- [ ] **步骤 2：运行测试**

`uv run pytest tests/test_summarizer.py -v`

- [ ] **步骤 3：Commit**

```bash
git add tests/test_summarizer.py
git commit -m "test: add summarizer immutability and exception tests"
```

---

### 任务 19：扩展 test_memory_bank.py

**文件：**
- 修改：`tests/test_memory_bank.py`

接口：现有测试基础上补充说话人过滤、合并去重场景。

新增测试用例：
- `test_speaker_filter_positive_score_downweight` — 正分 *0.75
- `test_speaker_filter_negative_score_upweight` — 负分 *1.25（实际远离零，使排名更低）
- `test_merge_overlapping_no_overlap` — 两份结果无共享索引 → 不合并

- [ ] **步骤 1：添加测试**

在现有测试文件中追加新测试函数。

- [ ] **步骤 2：运行测试**

`uv run pytest tests/test_memory_bank.py -v`

- [ ] **步骤 3：Commit**

```bash
git add tests/test_memory_bank.py
git commit -m "test: expand memory_bank tests with speaker filter and merge cases"
```

---

### 任务 20：最终集成验证

- [ ] **步骤 1：运行全部测试**

`uv run pytest tests/ -v --timeout=30`

- [ ] **步骤 2：运行 lint/type check**

```bash
uv run ruff check --fix && uv run ruff format && uv run ty check
```

- [ ] **步骤 3：修复所有失败的 lint/type 错误**

- [ ] **步骤 4：最终 Commit**

```bash
git add -A
git commit -m "chore: final integration verification and lint fixes"
```
